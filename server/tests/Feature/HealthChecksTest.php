<?php

declare(strict_types=1);

namespace Tests\Feature;

use App\Models\Setting;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Schema;
use Tests\Concerns\BuildsLab;
use Tests\TestCase;

/** S-55: the doctor command and the Health page show the same HealthChecks rows. */
class HealthChecksTest extends TestCase
{
    use BuildsLab, RefreshDatabase;

    /** @return list<array{check: string, ok: bool, level: string, detail: string, fix: string}> */
    private function doctorJson(?int &$exit = null): array
    {
        $exit = Artisan::call('xephyguard:doctor', ['--json' => true]);

        return json_decode(Artisan::output(), true, 512, JSON_THROW_ON_ERROR);
    }

    public function test_page_shows_the_same_checks_details_and_fixes_as_the_command(): void
    {
        $this->bootLab();
        $this->freezeTime();   // CA days-left and file times must not tick between command and page
        Http::fake(['*' => Http::response('down', 503)]);   // analysis service not answering
        $rows = $this->doctorJson($exit);

        $byName = array_column($rows, null, 'check');
        $this->assertSame(['ok' => false, 'level' => 'warning', 'fix' => 'docker compose logs analysis'],
            array_intersect_key($byName['Analysis service'], array_flip(['ok', 'level', 'fix'])));
        $this->assertSame(collect($rows)->contains('level', 'error') ? 1 : 0, $exit);

        $page = $this->actingAs($this->user('admin'))->get('/health')->assertOk();
        $page->assertDontSee('<b>Check</b>', false);   // the old page read keys Doctor never sent
        foreach ($rows as $r) {
            $page->assertSee($r['check'])->assertSee($r['detail']);
            if (! $r['ok']) {
                $page->assertSee('→ '.$r['fix']);
            }
        }
        $okCount = count(array_filter($rows, fn ($r) => $r['ok']));
        $page->assertSee("{$okCount} of ".count($rows), false);
    }

    public function test_a_check_that_throws_is_an_error_row_and_the_others_still_run(): void
    {
        $this->bootLab();
        Http::fake(['*' => Http::response('{}', 200)]);
        Schema::drop('jobs');

        $rows = $this->doctorJson($exit);
        $this->assertSame(1, $exit);
        $jobs = array_column($rows, null, 'check')['Background jobs'];
        $this->assertFalse($jobs['ok']);
        $this->assertSame('error', $jobs['level']);
        $this->assertStringStartsWith('Check could not run: ', $jobs['detail']);
        $this->assertSame('See storage/logs/laravel.log', $jobs['fix']);
        $names = array_column($rows, 'check');
        $this->assertSame(['Lab PCs reporting', 'Agent certificates', 'Time sync'], array_slice($names, -3));
        $this->assertSame('ok', array_column($rows, null, 'check')['Analysis service']['level']);

        $this->actingAs($this->user('admin'))->get('/health')->assertOk()
            ->assertSee('Check could not run: ')->assertSee('class="tick-bad"', false);
    }

    public function test_cli_output_escapes_details(): void
    {
        $this->bootLab();
        Http::fake(['*' => Http::response('{}', 200)]);
        config(['xephyguard.net_state_path' => sys_get_temp_dir().'/<error>xg-missing</error>/state.json']);

        $this->artisan('xephyguard:doctor')
            ->expectsOutputToContain('Missing: '.sys_get_temp_dir().'/<error>xg-missing</error>/state.json');
    }

    /** S-63 (proxy Steps 23, 26): netpolicy's health.json and the proxy's proxy-stats.json are shown, read-only. */
    public function test_sidecar_health_and_proxy_counters_are_shown(): void
    {
        $this->bootLab();
        $this->freezeTime();
        Http::fake(['*' => Http::response('{}', 200)]);
        Setting::put('ccc_ip', '');   // skip the 1 s TCP probes: this test calls the doctor many times
        $dir = sys_get_temp_dir().'/xg-health-'.uniqid();
        mkdir($dir);
        config(['xephyguard.net_state_path' => "$dir/state.json", 'xephyguard.proxy_stats_path' => "$dir/proxy-stats.json"]);
        $row = function (string $name): array {
            return array_column($this->doctorJson(), null, 'check')[$name];
        };
        $put = fn (string $f, array $doc) => file_put_contents("$dir/$f", json_encode($doc));

        try {
            // neither file yet: warnings, not errors
            $this->assertSame(['ok' => false, 'level' => 'warning'], array_intersect_key($row('Gateway firewall sets'), ['ok' => 0, 'level' => 0]));
            $this->assertSame('No proxy-stats.json from the proxy yet', $row('Proxy event delivery')['detail']);

            $put('health.json', ['nft_ok' => false, 'nft_error' => 'Error: Could not process rule', 'nft_skipped' => null,
                'nft_failed_since' => '2026-11-25T08:00:00Z', 'nft_checked_at' => '2026-11-25T09:00:00Z']);
            $r = $row('Gateway firewall sets');
            $this->assertSame([false, 'error'], [$r['ok'], $r['level']]);
            $this->assertSame('Loading the firewall sets fails since 2026-11-25T08:00:00Z: Error: Could not process rule', $r['detail']);
            $this->assertSame(1, Artisan::call('xephyguard:doctor', ['--json' => true]));   // an error row fails the doctor

            $put('health.json', ['nft_ok' => true, 'nft_checked_at' => '2026-11-25T09:05:00Z']);
            $this->assertSame([true, 'Firewall sets loaded (checked 2026-11-25T09:05:00Z)'], [$row('Gateway firewall sets')['ok'], $row('Gateway firewall sets')['detail']]);
            $put('health.json', ['nft_ok' => null, 'nft_skipped' => 'proxy_only mode']);
            $this->assertSame('Not used: proxy_only mode', $row('Gateway firewall sets')['detail']);

            $stats = ['spilled' => 40, 'replayed' => 30, 'rejected' => 0, 'purged' => 0, 'spill_lost' => 0, 'queue_full' => 0,
                'deduped_allowed' => 7, 'deduped_observed' => 2, 'queued' => 3, 'updated_at' => now()->getTimestamp() - 30];
            $put('proxy-stats.json', $stats);
            $r = $row('Proxy event delivery');
            $this->assertSame([true, '3 queued, 10 waiting for replay, 30 replayed, 0 refused, 0 lost, 9 repeats skipped'], [$r['ok'], $r['detail']]);
            $put('proxy-stats.json', ['queue_full' => 5, 'spill_lost' => 1] + $stats);
            $this->assertStringContainsString('6 lost', $row('Proxy event delivery')['detail']);
            $this->assertSame([false, 'warning'], [$row('Proxy event delivery')['ok'], $row('Proxy event delivery')['level']]);
            $put('proxy-stats.json', ['updated_at' => now()->getTimestamp() - 900] + $stats);
            $this->assertStringStartsWith('Proxy counters not updated for 15 minutes: ', $row('Proxy event delivery')['detail']);
            file_put_contents("$dir/proxy-stats.json", '[1, 2]');   // not an object
            $this->assertSame('No proxy-stats.json from the proxy yet', $row('Proxy event delivery')['detail']);

            $this->actingAs($this->user('admin'))->get('/health')->assertOk()
                ->assertSee('Gateway firewall sets')->assertSee('Not used: proxy_only mode')->assertSee('Proxy event delivery');
        } finally {
            array_map('unlink', glob("$dir/*"));
            rmdir($dir);
        }
    }
}
