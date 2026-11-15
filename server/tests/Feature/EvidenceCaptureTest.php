<?php

namespace Tests\Feature;

use App\Jobs\PurgeRetention;
use App\Models\AuditLog;
use App\Models\EvidenceCapture;
use App\Models\LabSession;
use App\Models\Profile;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Storage;
use Tests\Concerns\BuildsLab;
use Tests\TestCase;

class EvidenceCaptureTest extends TestCase
{
    use BuildsLab, RefreshDatabase;

    private function tinyPng(): string
    {
        return base64_decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
        );
    }

    public function test_instructor_can_upload_view_and_report_screen_evidence(): void
    {
        Storage::fake('local');
        $lab = $this->bootLab();
        [$pc] = $this->enrolledPc();
        $pc->update(['current_user' => 'alice', 'status' => 'normal', 'last_seen_at' => now()]);

        $instructor = $this->user('instructor');
        $profile = Profile::query()->where('mode', 'test')->firstOrFail();
        $session = LabSession::create([
            'lab_id' => $lab->id,
            'profile_id' => $profile->id,
            'started_by' => $instructor->id,
            'course' => 'CS202',
            'mode' => 'test',
            'status' => 'active',
            'starts_at' => now()->subMinutes(10),
        ]);

        $png = $this->tinyPng();
        $file = UploadedFile::fake()->createWithContent('snap.png', $png);

        $this->postJson(route('pcs.evidence', $pc), ['image' => $file])->assertUnauthorized();

        $res = $this->actingAs($instructor)
            ->post(route('pcs.evidence', $pc), [
                'image' => $file,
                'monitor' => 1,
                'source_mode' => 'live',
                'note' => 'Visible ChatGPT tab',
            ], ['Accept' => 'application/json']);

        $res->assertCreated()
            ->assertJsonPath('ok', true)
            ->assertJsonPath('evidence.monitor', 1)
            ->assertJsonPath('evidence.source_mode', 'live')
            ->assertJsonPath('evidence.user', 'alice')
            ->assertJsonPath('evidence.sha256', hash('sha256', $png))
            ->assertJsonPath('evidence.size_bytes', strlen($png));

        $capture = EvidenceCapture::query()->firstOrFail();
        Storage::disk('local')->assertExists($capture->file_path);
        $this->assertSame($png, Storage::disk('local')->get($capture->file_path));
        $this->assertDatabaseHas('audit_log', [
            'action' => 'pc.evidence',
            'subject_id' => $pc->id,
        ]);

        $this->actingAs($instructor)
            ->getJson(route('pcs.show', $pc))
            ->assertOk()
            ->assertJsonPath('evidence.0.id', $capture->id)
            ->assertJsonPath('evidence.0.sha256', hash('sha256', $png));

        $imgRes = $this->actingAs($instructor)->get(route('evidence.show', $capture));
        $imgRes->assertOk()->assertHeader('Content-Type', 'image/png');
        $this->assertSame($png, $imgRes->streamedContent());

        $this->actingAs($instructor)
            ->get(route('reports.show', $session))
            ->assertOk()
            ->assertSee('Saved screen evidence (1)')
            ->assertSee(substr($capture->sha256, 0, 12));

        $this->actingAs($instructor)
            ->get(route('reports.pdf', $session))
            ->assertOk()
            ->assertHeader('content-type', 'application/pdf');
    }

    public function test_invalid_file_is_rejected_and_retention_purges_expired_evidence(): void
    {
        Storage::fake('local');
        $this->bootLab();
        [$pc] = $this->enrolledPc();
        $assistant = $this->user('assistant');

        $bad = UploadedFile::fake()->createWithContent('notes.txt', 'not a png');
        $this->actingAs($assistant)
            ->post(route('pcs.evidence', $pc), ['image' => $bad], ['Accept' => 'application/json'])
            ->assertUnprocessable();

        $png = $this->tinyPng();
        $good = UploadedFile::fake()->createWithContent('old.png', $png);
        $this->actingAs($assistant)
            ->post(route('pcs.evidence', $pc), ['image' => $good], ['Accept' => 'application/json'])
            ->assertCreated();

        $capture = EvidenceCapture::query()->firstOrFail();
        $capture->forceFill(['occurred_at' => now()->subDays(200)])->save();
        Storage::disk('local')->assertExists($capture->file_path);

        (new PurgeRetention())->handle();

        Storage::disk('local')->assertMissing($capture->file_path);
        $this->assertDatabaseMissing('evidence_captures', ['id' => $capture->id]);
        $this->assertGreaterThan(0, AuditLog::query()->where('action', 'retention.purge')->count());
    }
}
