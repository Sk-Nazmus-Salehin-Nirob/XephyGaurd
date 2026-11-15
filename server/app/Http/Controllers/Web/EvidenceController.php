<?php

namespace App\Http\Controllers\Web;

use App\Http\Controllers\Controller;
use App\Models\EvidenceCapture;
use App\Models\LabSession;
use App\Models\Pc;
use App\Services\Audit;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Str;
use Symfony\Component\HttpFoundation\StreamedResponse;

/** Handles storing and streaming instructor-captured screenshot evidence. */
class EvidenceController extends Controller
{
    public function store(Request $request, Pc $pc): JsonResponse
    {
        $d = $request->validate([
            'image' => 'required|file|mimes:png,webp,jpeg,jpg|max:8192',
            'monitor' => 'nullable|integer|min:0|max:15',
            'source_mode' => 'nullable|string|in:snapshot,live',
            'note' => 'nullable|string|max:500',
        ]);

        $file = $request->file('image');
        $bytes = file_get_contents($file->getRealPath());
        if ($bytes === false || $bytes === '') {
            return response()->json(['message' => 'Uploaded image is empty.'], 422);
        }

        $ext = strtolower($file->guessExtension() ?: $file->extension() ?: 'png');
        $ext = match ($ext) {
            'jpeg', 'jpg' => 'jpg',
            'webp' => 'webp',
            default => 'png',
        };
        $mime = match ($ext) {
            'jpg' => 'image/jpeg',
            'webp' => 'image/webp',
            default => 'image/png',
        };

        $sha256 = hash('sha256', $bytes);
        $size = strlen($bytes);
        $path = 'evidence/pc_'.$pc->id.'/'.Str::uuid().'.'.$ext;

        Storage::disk('local')->put($path, $bytes);

        $session = LabSession::query()->where('status', 'active')->first();
        $capture = EvidenceCapture::create([
            'pc_id' => $pc->id,
            'lab_session_id' => $session?->id,
            'user' => $pc->current_user,
            'captured_by' => $request->user()?->id,
            'monitor' => (int) ($d['monitor'] ?? 0),
            'source_mode' => $d['source_mode'] ?? 'snapshot',
            'file_path' => $path,
            'mime_type' => $mime,
            'sha256' => $sha256,
            'size_bytes' => $size,
            'note' => $d['note'] ?? null,
            'occurred_at' => now(),
        ]);
        $capture->load('capturer:id,name');

        Audit::log('pc.evidence', $pc, [
            'evidence_id' => $capture->id,
            'monitor' => $capture->monitor,
            'source_mode' => $capture->source_mode,
            'sha256' => $sha256,
            'size_bytes' => $size,
        ]);

        return response()->json([
            'ok' => true,
            'evidence' => $capture->toApiArray(),
        ], 201);
    }

    public function show(EvidenceCapture $capture): StreamedResponse
    {
        if (! Storage::disk('local')->exists($capture->file_path)) {
            abort(404);
        }

        return Storage::disk('local')->response($capture->file_path, 'evidence-'.$capture->id, [
            'Content-Type' => $capture->mime_type,
            'X-Content-Type-Options' => 'nosniff',
        ], 'inline');
    }
}
