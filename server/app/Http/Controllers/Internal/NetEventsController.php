<?php

namespace App\Http\Controllers\Internal;

use App\Events\AlertRaised;
use App\Events\PcUpdated;
use App\Http\Controllers\Controller;
use App\Models\Alert;
use App\Models\LabSession;
use App\Models\NetEvent;
use App\Models\Pc;
use App\Models\SessionPc;
use App\Services\EventIngestor;
use Carbon\CarbonImmutable;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

/** Receives blocked/allowed/observed network events from the proxy addon (and DNS log shipper). */
class NetEventsController extends Controller
{
    public function store(Request $request, EventIngestor $ingestor): JsonResponse
    {
        $data = $request->validate([
            'events' => 'required|array|max:1000',
            'events.*.client_ip' => 'required|ip',
            'events.*.host' => 'nullable|string|max:255',
            'events.*.path' => 'nullable|string|max:512',
            'events.*.layer' => 'required|string|max:16',
            'events.*.action' => 'required|in:blocked,allowed,rewritten,observed',
            'events.*.category' => 'nullable|string|max:24',
            'events.*.matched' => 'nullable|string|max:255',
            'events.*.ts' => 'nullable|integer',
        ]);
        $normIp = fn (string $ip): string => str_starts_with($ip, '::ffff:') ? substr($ip, 7) : $ip;
        $ips = collect($data['events'])->map(fn ($e) => $normIp($e['client_ip']))->unique();
        $pcs = Pc::query()->active()->whereIn('ip', $ips)->get()->keyBy('ip');
        $now = now()->toImmutable();
        $ats = array_map(fn ($e) => isset($e['ts'])
            ? CarbonImmutable::createFromTimestampMs($e['ts'], config('app.timezone')) : $now, $data['events']);
        $from = min([$now, ...$ats]);
        $to = max([$now, ...$ats]);
        // An event belongs to the session that was running at its ts, not to the one active when it arrives:
        // the proxy replays spilled events after an outage, possibly from an earlier session (proxy Step 25, S-61).
        $candidates = [];
        $rows = [];
        $dirtyPcs = [];
        $alerts = [];
        $seenAlertKeys = [];
        $pcsNeedingScore = [];
        $active = [];
        foreach ($data['events'] as $i => $e) {
            $clientIp = $normIp($e['client_ip']);
            $pc = $pcs[$clientIp] ?? null;
            $at = $ats[$i];
            $session = null;
            $sid = null;
            if ($pc) {
                $candidates[$pc->lab_id] ??= LabSession::runningBetween($pc->lab_id, $from, $to);
                $session = $candidates[$pc->lab_id]->first(fn (LabSession $s) => $s->ranAt($at));
                $sid = $session?->id;
            }
            $rows[] = [
                'pc_id' => $pc?->id, 'lab_session_id' => $sid, 'client_ip' => $clientIp,
                'host' => $e['host'] ?? '', 'path' => $e['path'] ?? null, 'layer' => $e['layer'], 'action' => $e['action'],
                'category' => $e['category'] ?? null, 'matched' => $e['matched'] ?? null,
                'occurred_at' => $at,
            ];
            if (! $pc) {
                continue;
            }
            if ($e['action'] === 'blocked') {
                $pc->last_event = mb_substr('Blocked: '.($e['host'] ?? ''), 0, 160);
                $dirtyPcs[$pc->id] = $pc;
            } elseif ($e['action'] === 'observed' && in_array($e['category'] ?? '', ['ai', 'ide'], true)) {
                $prefix = ($e['category'] === 'ide') ? 'IDE AI traffic: ' : 'AI traffic: ';
                $hostOrMatched = ($e['host'] ?? '') ?: ($e['matched'] ?? '');
                $pc->last_event = mb_substr($prefix.$hostOrMatched, 0, 160);
                $dirtyPcs[$pc->id] = $pc;

                $ruleId = $e['category'] === 'ide' ? 'proxy.ide_ai_observed' : 'proxy.ai_observed';
                $label = $e['category'] === 'ide' ? 'IDE AI backend traffic' : 'AI service traffic';
                $subject = ($e['matched'] ?? '') ?: ($e['host'] ?? '');
                $title = mb_substr("{$label}: {$subject} (proxy)", 0, 200);
                $dedupKey = "{$pc->id}|{$sid}|{$ruleId}|{$title}";
                if (! isset($seenAlertKeys[$dedupKey])) {
                    $seenAlertKeys[$dedupKey] = true;
                    $dup = Alert::query()->where('pc_id', $pc->id)->where('lab_session_id', $sid)
                        ->where('rule_id', $ruleId)->where('title', $title)
                        ->where('occurred_at', '>', $at->subMinutes(30))->exists();
                    if (! $dup) {
                        $alert = Alert::create([
                            'pc_id' => $pc->id, 'lab_session_id' => $sid, 'rule_id' => $ruleId,
                            'severity' => 'high', 'category' => $e['category'],
                            'title' => $title,
                            'details' => [
                                'host' => $e['host'] ?? '',
                                'matched' => $e['matched'] ?? null,
                                'layer' => $e['layer'],
                                'source' => 'proxy',
                            ],
                            'user' => $pc->current_user,
                            'occurred_at' => $at,
                        ]);
                        $alert->setRelation('pc', $pc);
                        $alerts[] = $alert;
                        $pcsNeedingScore[$pc->id] = true;
                    }
                }
            }
        }
        foreach (array_chunk($rows, 200) as $chunk) {
            NetEvent::query()->insert($chunk);
        }
        foreach ($dirtyPcs as $pcId => $pc) {
            if (isset($pcsNeedingScore[$pcId])) {
                // the live score is about now: the session active now, whatever session the alert went to
                $active[$pc->lab_id] ??= LabSession::activeFor($pc->lab_id) ?? false;
                $sess = $active[$pc->lab_id] ?: null;
                $inSess = $sess && SessionPc::query()->where('lab_session_id', $sess->id)->where('pc_id', $pc->id)->exists();
                $ingestor->refreshLiveScore($pc, $inSess ? $sess : null);
            }
            $pc->save();
            broadcast(new PcUpdated($pc));
        }
        foreach ($alerts as $alert) {
            broadcast(new AlertRaised($alert));
        }

        return response()->json(['stored' => count($rows)]);
    }
}
