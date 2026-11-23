<?php

declare(strict_types=1);

namespace Tests\Feature;

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
}
