<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\Pc;
use App\Models\Setting;
use App\Models\SignatureVersion;
use Illuminate\Database\Eloquent\Collection;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;

/**
 * Health checks with plain-language explanations. The one source for the dashboard "System health"
 * page and `php artisan xephyguard:doctor`: both show these rows with the same fields. Host-level
 * checks (IP forwarding, nftables) are in ccc-deploy/bin/xephyguard-ccc doctor, which also calls this.
 */
class HealthChecks
{
    /** @var Collection<int, Pc>|null */
    private ?Collection $pcs = null;

    /**
     * Every check runs on its own: one that throws is reported as an error row and the rest still run.
     *
     * @return list<array{check: string, ok: bool, level: string, detail: string, fix: string}>
     */
    public function run(): array
    {
        $r = [];
        $add = function (string $check, string $fix, string $level, \Closure $probe) use (&$r): void {
            try {
                // probe returns [ok, detail] or [ok, detail, fix, level] to override the defaults
                $out = $probe();
                [$ok, $detail] = $out;
                $fix = $out[2] ?? $fix;
                $level = $out[3] ?? $level;
            } catch (\Throwable $e) {
                report($e);
                [$ok, $detail, $fix, $level] = [false, 'Check could not run: '.Str::limit($e->getMessage(), 200),
                    'See storage/logs/laravel.log', 'error'];
            }
            $r[] = ['check' => $check, 'ok' => $ok, 'level' => $ok ? 'ok' : $level, 'detail' => $detail, 'fix' => $ok ? '' : $fix];
        };

        $add('Database', 'Check the mysql container: docker compose ps mysql', 'error', function () {
            DB::select('select 1');

            return [true, 'Connected to '.DB::connection()->getDriverName()];
        });

        $add('Lab certificate authority', 'Run: php artisan xephyguard:ca:init', 'error', function () {
            $ca = CertificateAuthority::fromConfig();
            if (! $ca->exists()) {
                return [false, 'No CA found in '.$ca->dir()];
            }
            $days = (int) floor(($ca->expiresAt()->getTimestamp() - now()->getTimestamp()) / 86400);

            return [$days > 60, "CA valid for $days more days (fingerprint ".substr($ca->fingerprint(), 0, 16).'…)',
                'Plan a CA rotation and re-install the CA on lab PCs', 'warning'];
        });

        $add('Detection signatures', 'Open Signatures and press "Publish", or run php artisan xephyguard:signatures:publish', 'error', function () {
            $sig = SignatureVersion::active();

            return [(bool) $sig, $sig ? "Active version {$sig->version}" : 'No signature bundle published'];
        });

        $add('Network policy file', 'Run php artisan xephyguard:net:write and check the netpolicy container logs', 'error', function () {
            $state = (string) config('xephyguard.net_state_path');
            $fresh = is_file($state);

            return [$fresh, $fresh ? 'Written '.date('Y-m-d H:i:s', (int) filemtime($state)) : "Missing: $state"];
        });

        $add('Proxy reachable', 'docker compose logs proxy', 'warning', function () {
            $ok = $this->tcp(Setting::get('ccc_ip'), (int) config('xephyguard.proxy_port'));

            return [$ok, $ok ? 'Transparent proxy is listening' : 'Nothing listens on the proxy port'];
        });

        $add('Lab DNS resolver', 'docker compose logs dns; make sure systemd-resolved does not hold port 53 (install.sh disables its stub listener)', 'warning', function () {
            $ok = $this->tcp(Setting::get('ccc_ip'), 53);

            return [$ok, $ok ? 'Resolver answers on port 53' : 'Resolver not reachable on port 53'];
        });

        $add('Gateway firewall sets', 'docker compose logs netpolicy; check the gateway ruleset with: nft list table inet xephyguard', 'error', function () {
            $h = $this->readJson($this->netHealthPath());
            if ($h === null) {
                return [false, 'No health.json from netpolicy yet', 'docker compose logs netpolicy', 'warning'];
            }
            $at = is_string($h['nft_checked_at'] ?? null) ? ' (checked '.$h['nft_checked_at'].')' : '';
            if (($h['nft_ok'] ?? null) === false) {
                $since = is_string($h['nft_failed_since'] ?? null) ? ' since '.$h['nft_failed_since'] : '';

                return [false, "Loading the firewall sets fails{$since}: ".Str::limit((string) ($h['nft_error'] ?? 'no message'), 200)];
            }
            if (($h['nft_ok'] ?? null) === true) {
                return [true, 'Firewall sets loaded'.$at];
            }

            return [true, 'Not used: '.Str::limit((string) ($h['nft_skipped'] ?? 'not loaded'), 100).$at];
        });

        $add('Proxy event delivery', 'docker compose logs proxy; check the CCC answers on /api/internal/net-events', 'warning', function () {
            $s = $this->readJson($this->proxyStatsPath());
            if ($s === null) {
                return [false, 'No proxy-stats.json from the proxy yet'];
            }
            $n = fn (string $k): int => is_int($s[$k] ?? null) ? $s[$k] : 0;
            $lost = $n('queue_full') + $n('spill_lost');
            $waiting = max(0, $n('spilled') - $n('replayed') - $n('purged'));
            $age = is_int($s['updated_at'] ?? null) ? now()->getTimestamp() - $s['updated_at'] : null;
            $detail = sprintf('%d queued, %d waiting for replay, %d replayed, %d refused, %d lost, %d repeats skipped',
                $n('queued'), $waiting, $n('replayed'), $n('rejected'), $lost, $n('deduped_allowed') + $n('deduped_observed'));
            if ($age === null || $age > 300) {
                return [false, 'Proxy counters not updated for '.($age === null ? 'an unknown time' : intdiv($age, 60).' minutes').": $detail"];
            }

            return [$lost === 0 && $n('rejected') === 0, $detail];   // counters since the proxy started
        });

        $add('Disk space', 'Free disk space or shorten raw-event retention in Settings', 'warning', function () {
            $gb = self::gb($this->disk()['free']);

            return [$gb > 5, "$gb GB free"];
        });

        $add('Analysis service', 'docker compose logs analysis', 'warning', function () {
            $ok = app(AnalysisClient::class)->health();

            return [$ok, $ok ? 'Behavioral scoring service answers' : 'Behavioral scoring service does not answer'];
        });

        $add('Background jobs', 'docker compose logs worker', 'warning', function () {
            $backlog = DB::table('jobs')->count();

            return [$backlog < 100, "$backlog queued jobs"];
        });

        $add('Lab PCs reporting', 'Check those PCs are powered on and the agent service is running', 'warning', function () {
            $silent = Pc::query()->active()->where('last_seen_at', '<', now()->subMinutes(10))->count();

            return [$silent === 0, $silent ? "$silent PCs have not reported for 10+ minutes" : 'All enrolled PCs reporting'];
        });

        $add('Agent certificates', 'Re-enroll the affected PCs', 'warning', function () {
            $n = $this->activePcs()->filter(fn ($p) => $p->agent && $p->agent->cert_expires_at?->lt(now()->addDays(30)))->count();

            return [$n === 0, $n ? "$n agent certificates expire within 30 days" : 'All agent certificates valid'];
        });

        $add('Time sync', 'Enable NTP on the lab PCs (the CCC still corrects event times)', 'warning', function () {
            $n = $this->activePcs()->filter(fn ($p) => abs($p->agent?->clock_offset_ms ?? 0) > 60000)->count();

            return [$n === 0, $n ? "$n PCs have a clock more than 1 minute off" : 'PC clocks agree with the CCC'];
        });

        return $r;
    }

    /**
     * Active PCs with their agent, loaded once per instance (checks and the health page share it).
     *
     * @return Collection<int, Pc>
     */
    public function activePcs(): Collection
    {
        return $this->pcs ??= Pc::query()->active()->with('agent')->get();
    }

    /** @return array{free: float|null, total: float|null} bytes on the storage volume, null when unknown */
    public function disk(): array
    {
        $free = @disk_free_space(storage_path());
        $total = @disk_total_space(storage_path());

        return ['free' => $free === false ? null : $free, 'total' => $total === false ? null : $total];
    }

    /** Bytes to GB (1024^3, like `df -BG` in xephyguard-ccc doctor), one decimal. */
    public static function gb(?float $bytes): float
    {
        return $bytes ? round($bytes / 1073741824, 1) : 0.0;
    }

    /** netpolicy's health.json (result of the last `nft -f`, proxy Step 23), next to state.json. */
    public function netHealthPath(): string
    {
        return (string) (config('xephyguard.net_health_path') ?: dirname((string) config('xephyguard.net_state_path')).'/health.json');
    }

    /** The proxy's proxy-stats.json (event shipper counters, proxy Step 26): counts only, no hosts or IPs. */
    public function proxyStatsPath(): string
    {
        return (string) config('xephyguard.proxy_stats_path');
    }

    /** @return array<string, mixed>|null the decoded JSON object, or null when missing, unreadable or not an object */
    private function readJson(string $path): ?array
    {
        if ($path === '' || ! is_file($path) || ($text = @file_get_contents($path)) === false) {
            return null;
        }
        $doc = json_decode($text, true);

        return is_array($doc) && ! array_is_list($doc) ? $doc : null;
    }

    private function tcp(mixed $host, int $port): bool
    {
        if (! is_string($host) || $host === '') {
            return false;
        }
        $s = @fsockopen($host, $port, $errno, $errstr, 1.0);
        if ($s) {
            fclose($s);

            return true;
        }

        return false;
    }
}
