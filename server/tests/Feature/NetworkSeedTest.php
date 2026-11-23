<?php

declare(strict_types=1);

namespace Tests\Feature;

use App\Models\Setting;
use App\Services\Bootstrap;
use App\Services\NetworkPolicyWriter;
use App\Services\NetworkSeed;
use App\Services\SignatureCompiler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\File;
use Symfony\Component\Yaml\Yaml;
use Tests\Concerns\BuildsLab;
use Tests\TestCase;

/** S-53 (I-SERVER-36): proxy lists and agent probe/scan blocks come from data/ YAML, not server code. */
class NetworkSeedTest extends TestCase
{
    use BuildsLab, RefreshDatabase;

    private const FORM = ['lab_name' => 'Lab', 'network_mode' => 'gateway', 'ccc_ip' => '192.168.10.1', 'lab_subnet' => '192.168.10.0/24',
        'retention_days_raw' => 30, 'retention_days_reports' => 365, 'notice_text' => 'Monitored.', 'paste_alert_chars' => 800,
        'title_capture_always_on' => 'off', 'title_capture_practice' => 'app_only', 'title_capture_test' => 'app_only'];

    private function seedFile(): array
    {
        return Yaml::parseFile(config('xephyguard.data_dir').'/network/proxy.yaml');
    }

    public function test_state_lists_follow_the_yaml_and_a_changed_file(): void
    {
        $this->bootLab();
        $state = app(NetworkPolicyWriter::class)->build();
        $this->assertSame($this->seedFile()['inspect_hosts'], $state['inspect_hosts']);
        $this->assertSame($this->seedFile()['google_hide_selectors'], $state['google']['hide_selectors']);
        $this->assertNull(Setting::get('google_hide_selectors'));   // bootstrap no longer stores a copy

        $dir = storage_path('framework/testing/seed-'.uniqid());
        File::ensureDirectoryExists("$dir/network");
        File::put("$dir/network/proxy.yaml", "inspect_hosts: [search.example]\ngoogle_hide_selectors: ['.ai-box']\n");
        try {
            config(['xephyguard.data_dir' => $dir]);
            $state = app(NetworkPolicyWriter::class)->build();
            $this->assertSame(['search.example'], $state['inspect_hosts']);
            $this->assertSame(['.ai-box'], $state['google']['hide_selectors']);
        } finally {
            File::deleteDirectory($dir);
        }
    }

    public function test_settings_override_only_when_changed(): void
    {
        $this->bootLab();
        $admin = $this->user('admin');
        $seedHosts = implode("\n", $this->seedFile()['inspect_hosts']);

        $this->actingAs($admin)->get('/settings')->assertOk()->assertSee('search.brave.com');
        $this->actingAs($admin)->post('/settings', self::FORM + ['inspect_hosts' => $seedHosts, 'google_hide_selectors' => ''])
            ->assertSessionHasNoErrors();
        $this->assertNull(Setting::get('inspect_hosts'));            // unchanged: still follows the seed
        $this->assertNull(Setting::get('google_hide_selectors'));    // empty: seed

        $this->actingAs($admin)->post('/settings', self::FORM + ['inspect_hosts' => "a.example\n b.example \na.example", 'google_hide_selectors' => '.x'])
            ->assertSessionHasNoErrors();
        $state = app(NetworkPolicyWriter::class)->build();
        $this->assertSame(['a.example', 'b.example'], $state['inspect_hosts']);
        $this->assertSame(['.x'], $state['google']['hide_selectors']);

        $this->actingAs($admin)->post('/settings', self::FORM + ['inspect_hosts' => '', 'google_hide_selectors' => ''])
            ->assertSessionHasNoErrors();
        $this->assertSame($this->seedFile()['inspect_hosts'], NetworkSeed::get('inspect_hosts'));
    }

    public function test_bootstrap_drops_stored_copies_equal_to_the_seed_and_keeps_edits(): void
    {
        $this->bootLab();
        Setting::put('google_hide_selectors', $this->seedFile()['google_hide_selectors']);   // written by the old bootstrap
        Setting::put('inspect_hosts', ['only.example']);                                // admin edit

        app(Bootstrap::class)->run();

        $this->assertNull(Setting::get('google_hide_selectors'));
        $this->assertSame(['only.example'], Setting::get('inspect_hosts'));
    }

    public function test_bundle_probe_and_scan_come_from_the_yaml_before_any_import(): void
    {
        $this->bootLab();
        Setting::forget('signatures.port.probe');
        Setting::forget('signatures.artifact.scan');
        $dir = config('xephyguard.data_dir').'/signatures';

        $bundle = app(SignatureCompiler::class)->buildBundle();
        $this->assertSame(Yaml::parseFile("$dir/ports.yaml")['probe'], $bundle['ports']['probe']);
        $this->assertSame(Yaml::parseFile("$dir/artifacts.yaml")['scan'], $bundle['artifacts']['scan']);

        config(['xephyguard.data_dir' => storage_path('framework/testing/no-such-dir')]);
        $bundle = app(SignatureCompiler::class)->buildBundle();
        $this->assertArrayNotHasKey('probe', $bundle['ports']);      // no hard-coded fallback
        $this->assertArrayNotHasKey('scan', $bundle['artifacts']);
    }
}
