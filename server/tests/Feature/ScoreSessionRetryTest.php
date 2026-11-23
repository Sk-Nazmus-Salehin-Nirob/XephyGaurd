<?php

declare(strict_types=1);

namespace Tests\Feature;

use App\Jobs\ScoreSession;
use App\Models\LabSession;
use App\Models\Report;
use App\Services\AnalysisClient;
use App\Services\AnalysisFailed;
use App\Services\SessionManager;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Tests\Concerns\BuildsLab;
use Tests\TestCase;

/** S-54: the analysis service has its own token, and only transient errors are retried (F111, I-ANALYSIS-17). */
class ScoreSessionRetryTest extends TestCase
{
    use BuildsLab, RefreshDatabase;

    private function labSession(): LabSession
    {
        return app(SessionManager::class)->start($this->bootLab(), $this->profile('Test: AI blocked'), 'CS101');
    }

    public function test_scoring_sends_the_analysis_token_not_the_internal_token(): void
    {
        $s = $this->labSession();
        Http::fake(['analysis.test/score' => Http::response(['scored' => 2, 'flagged' => []])]);

        ScoreSession::dispatch($s->id);

        Http::assertSent(fn (Request $r) => $r->url() === 'http://analysis.test/score'
            && $r->hasHeader('Authorization', 'Bearer test-analysis-token') && $r['session_id'] === $s->id);
        Http::assertNotSent(fn (Request $r) => str_contains($r->header('Authorization')[0] ?? '', 'test-internal-token'));
        $this->assertDatabaseHas('reports', ['lab_session_id' => $s->id, 'status' => 'ready']);
    }

    public function test_transient_errors_are_thrown_for_a_retry_and_leave_the_report_queued(): void
    {
        $s = $this->labSession();
        $answer = null;
        Http::fake(['analysis.test/*' => function () use (&$answer) {
            return $answer();
        }]);
        foreach (['unreachable' => fn () => throw new ConnectionException('down'), 'HTTP 503' => fn () => Http::response(['error' => 'x'], 503),
            'HTTP 429' => fn () => Http::response([], 429), 'no JSON' => fn () => Http::response('<html>', 200)] as $reason => $answer) {
            $job = (new ScoreSession($s->id))->withFakeQueueInteractions();
            try {
                $job->handle(app(AnalysisClient::class));
                $this->fail('no exception');
            } catch (AnalysisFailed $e) {
                $this->assertTrue($e->retryable, $e->getMessage());
                $this->assertStringContainsString($reason, $e->getMessage());
            }
            $job->assertNotFailed();
            $this->assertDatabaseHas('reports', ['lab_session_id' => $s->id, 'status' => 'queued']);
        }
    }

    public function test_a_refused_request_fails_at_once_with_the_reason_in_the_report(): void
    {
        $s = $this->labSession();
        $code = 0;
        Http::fake(['analysis.test/*' => function () use (&$code) {
            return Http::response(['error' => $code === 404 ? "'session 99'" : 'bad'], $code);
        }]);
        foreach ([401 => 'HTTP 401): bad', 404 => "HTTP 404): 'session 99'", 422 => 'HTTP 422): bad'] as $code => $reason) {
            $job = (new ScoreSession($s->id))->withFakeQueueInteractions();
            $job->handle(app(AnalysisClient::class));
            $job->assertFailed();

            ScoreSession::dispatch($s->id);   // sync queue: fail() runs failed()
            $report = Report::query()->where(['lab_session_id' => $s->id, 'kind' => 'session'])->sole();
            $this->assertSame('failed', $report->status);
            $this->assertStringContainsString($reason, $report->summary['error']);
        }
    }

    public function test_a_missing_short_or_reused_token_never_calls_the_service(): void
    {
        $s = $this->labSession();
        Http::fake();
        foreach (['' => 'not set', 'short-token' => 'shorter than 16', 'test-internal-token' => 'must differ'] as $token => $reason) {
            config(['xephyguard.analysis_token' => $token]);
            ScoreSession::dispatch($s->id);
            $this->assertStringContainsString($reason, Report::query()->where(['lab_session_id' => $s->id, 'kind' => 'session'])->sole()->summary['error']);
        }
        Http::assertNothingSent();
    }

    public function test_a_deleted_session_fails_without_a_call_or_a_report(): void
    {
        Http::fake();
        $job = (new ScoreSession(999))->withFakeQueueInteractions();
        $job->handle(app(AnalysisClient::class));
        $job->assertFailed();
        $job->failed(new \RuntimeException('x'));
        Http::assertNothingSent();
        $this->assertDatabaseCount('reports', 0);
    }

    public function test_retry_budget_fits_the_backoff_and_the_queue_timeout(): void
    {
        $job = new ScoreSession(1);
        $this->assertSame(count($job->backoff) + 1, $job->tries);
        $this->assertGreaterThan(AnalysisClient::TIMEOUT_S, $job->timeout);
        $this->assertLessThan((int) config('queue.connections.database.retry_after'), $job->timeout);
    }

    public function test_the_analysis_token_does_not_open_the_internal_api(): void
    {
        $this->withToken('test-analysis-token')->getJson('/api/internal/eval/results')->assertUnauthorized();
        $this->withToken('test-analysis-token')->postJson('/api/internal/net-events', ['events' => []])->assertUnauthorized();
    }
}
