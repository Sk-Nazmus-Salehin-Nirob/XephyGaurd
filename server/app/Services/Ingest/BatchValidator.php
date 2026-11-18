<?php

namespace App\Services\Ingest;

use App\Models\Agent;
use Illuminate\Validation\ValidationException;

/** Checks an agent batch before EventIngestor stores anything: envelope, event shape, heartbeat values. */
class BatchValidator
{
    public const TYPES = ['heartbeat', 'agent_started', 'agent_stopping', 'process_start', 'process_stop',
        'process_snapshot', 'rule_hit', 'listening_port', 'window_focus', 'paste', 'copy', 'key_stats', 'net_adapter',
        'device', 'extension_scan', 'artifact_scan', 'file_activity', 'gpu_sample', 'tamper', 'capabilities',
        'command_result', 'helper_status'];

    public function validate(Agent $agent, array $b): void
    {
        $fail = fn (string $m) => throw ValidationException::withMessages(['batch' => $m]);
        if (($b['v'] ?? null) !== 1) {
            $fail('unsupported protocol version');
        }
        if ((string) ($b['pc_id'] ?? '') !== (string) $agent->pc_id) {
            $fail('pc_id does not match the authenticated agent');
        }
        $events = $b['events'] ?? [];
        if (! is_array($events) || count($events) > config('xephyguard.max_events_per_batch')) {
            $fail('events must be an array of at most '.config('xephyguard.max_events_per_batch'));
        }
        if (isset($b['heartbeat']) && ! is_array($b['heartbeat'])) {
            $fail('heartbeat must be an object');
        }
        foreach ($events as $i => $e) {
            if (! is_array($e) || ! is_int($e['seq'] ?? null) || $e['seq'] < 1 || ! is_int($e['ts'] ?? null)
                || ! in_array($e['type'] ?? null, self::TYPES, true) || ! is_array($e['data'] ?? null)) {
                $fail("event $i is malformed");
            }
            if (strlen(json_encode($e['data'])) > 64 * 1024) {
                $fail("event $i is too large");
            }
        }
    }

    /** Heartbeat usage.screen (screen Step 57): only the four known numbers, clamped; anything else is dropped. */
    public static function screenCost(mixed $s): ?array
    {
        if (! is_array($s)) {
            return null;
        }
        $out = [];
        foreach (['fps' => 1000, 'kbps' => 10000000, 'cpu_pct' => 1000, 'level' => 1000] as $k => $max) {
            if (isset($s[$k]) && (is_int($s[$k]) || is_float($s[$k])) && is_finite((float) $s[$k])) {
                $out[$k] = max(0, min($max, $s[$k]));
            }
        }

        return $out ?: null;
    }
}
