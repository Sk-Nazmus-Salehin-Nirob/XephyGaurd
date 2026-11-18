<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\Alert;
use App\Models\EvidenceCapture;
use App\Models\LabSession;
use App\Models\NetEvent;
use App\Models\PasteEvent;
use App\Models\Report;
use App\Models\Score;

/** Data of one session integrity report (F49-F51). Rendered by the HTML, PDF and CSV exports. */
class ReportModel
{
    public static function build(LabSession $session): array
    {
        $scores = Score::query()->with(['pc:id,name', 'student'])->where('lab_session_id', $session->id)
            ->orderByDesc('score')->get();

        return [
            'session' => $session->load('profile'),
            'scores' => $scores,
            'alerts' => Alert::query()->with('pc:id,name')->where('lab_session_id', $session->id)->orderBy('occurred_at')->get(),
            'blocked' => NetEvent::query()->where('lab_session_id', $session->id)->where('action', 'blocked')
                ->selectRaw('pc_id, host, category, count(*) as n, min(occurred_at) as first_at')
                ->groupBy('pc_id', 'host', 'category')->orderByDesc('n')->with('pc:id,name')->get(),
            'pastes' => PasteEvent::query()->where('lab_session_id', $session->id)->where('is_copy', false)
                ->where('chars', '>=', 300)->orderBy('occurred_at')->get(),
            'evidence' => EvidenceCapture::query()->with(['pc:id,name', 'capturer:id,name'])
                ->where('lab_session_id', $session->id)->orderBy('occurred_at')->get(),
            'report' => Report::query()->where('lab_session_id', $session->id)->where('kind', 'session')->first(),
        ];
    }
}
