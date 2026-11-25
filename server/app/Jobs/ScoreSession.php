<?php

declare(strict_types=1);

namespace App\Jobs;

use App\Models\Alert;
use App\Models\LabSession;
use App\Models\NetEvent;
use App\Models\Report;
use App\Services\AnalysisClient;
use App\Services\AnalysisFailed;
use Illuminate\Contracts\Queue\ShouldBeUnique;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Queue\Queueable;
use RuntimeException;

/** After a session ends: compute integrity scores (analysis service) and create the session report.
 * Transient analysis errors (down, timeout, 5xx, 429) are retried after 30 s, 2 min and 10 min;
 * a refused request (bad token, unknown session) fails at once and the report shows the reason.
 * Unique per session (S-65): while one is queued, waiting for a retry or running, another dispatch for the same
 * session (stop + rescore) is dropped, so two never score one session at once; the lock goes when it finishes or fails. */
class ScoreSession implements ShouldBeUnique, ShouldQueue
{
    use Queueable;

    /** One first try plus one retry per backoff value. */
    public int $tries = 4;

    public array $backoff = [30, 120, 600];

    /** Above AnalysisClient::TIMEOUT_S, below the queue's `retry_after` (90 s) so no attempt runs twice. */
    public int $timeout = 85;

    /** Seconds the unique lock may outlive a crashed worker: every attempt plus every backoff, rounded up. */
    public int $uniqueFor = 1200;

    public function __construct(public int $sessionId) {}

    public function uniqueId(): string
    {
        return (string) $this->sessionId;
    }

    public function handle(AnalysisClient $analysis): void
    {
        $session = LabSession::query()->find($this->sessionId);
        if ($session === null) {
            $this->fail(new RuntimeException("lab session {$this->sessionId} not found"));

            return;
        }
        $report = Report::query()->firstOrCreate(['lab_session_id' => $session->id, 'kind' => 'session'], ['status' => 'queued']);
        try {
            $result = $analysis->scoreSession($session->id);
        } catch (AnalysisFailed $e) {
            if ($e->retryable) {
                throw $e;
            }
            $this->fail($e);

            return;
        }
        $report->forceFill([
            'status' => 'ready',
            'summary' => [
                'scored' => $result['scored'] ?? 0,
                'flagged' => $result['flagged'] ?? [],
                'alerts' => Alert::query()->where('lab_session_id', $session->id)->count(),
                'blocked_attempts' => NetEvent::query()->where('lab_session_id', $session->id)->where('action', 'blocked')->count(),
                'generated_at' => now()->toIso8601String(),
            ],
        ])->save();
    }

    public function failed(?\Throwable $e): void
    {
        if (! LabSession::query()->whereKey($this->sessionId)->exists()) {
            return;
        }
        Report::query()->updateOrCreate(['lab_session_id' => $this->sessionId, 'kind' => 'session'],
            ['status' => 'failed', 'summary' => ['error' => mb_substr($e?->getMessage() ?? 'scoring failed', 0, 500)]]);
    }
}
