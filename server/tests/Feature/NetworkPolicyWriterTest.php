<?php

declare(strict_types=1);

namespace Tests\Feature;

use App\Models\Lab;
use App\Models\LabSession;
use App\Models\Pc;
use App\Models\Setting;
use App\Services\NetworkPolicyWriter;
use App\Services\NetworkSeed;
use App\Services\PolicyService;
use App\Services\SessionManager;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Queue;
use Symfony\Component\Yaml\Yaml;
use Tests\Concerns\BuildsLab;
use Tests\TestCase;

/** S-24: the state writer resolves every PC with a fixed query count and writes the file atomically, 0640. */
class NetworkPolicyWriterTest extends TestCase
{
    use BuildsLab, RefreshDatabase;

    private function pcs(int $from, int $count): void
    {
        for ($i = $from; $i < $from + $count; $i++) {
            Pc::create(['lab_id' => Lab::current()->id, 'name' => "PC-$i", 'hostname' => "pc-$i",
                'ip' => "192.168.10.$i", 'os' => 'Linux', 'macs' => []]);
        }
    }

    private function buildQueries(): int
    {
        $writer = app(NetworkPolicyWriter::class);
        $writer->build();   // warm the settings cache
        $n = 0;
        DB::listen(function () use (&$n) {
            $n++;
        });
        $writer->build();
        DB::getEventDispatcher()?->forget('Illuminate\Database\Events\QueryExecuted');

        return $n;
    }

    public function test_build_query_count_does_not_grow_with_pcs(): void
    {
        Queue::fake();
        $lab = $this->bootLab();
        $this->pcs(21, 1);
        $sm = app(SessionManager::class);
        $session = $sm->start($lab, $this->profile('Test: AI blocked'), 'CS101');
        // pcs, sessions, session profiles, links, override profiles, Always-on profile, blocklist
        $this->assertLessThanOrEqual(7, $this->buildQueries());
        $sm->stop($session);

        $this->pcs(22, 9);
        $session = $sm->start($lab, $this->profile('Test: AI blocked'), 'CS101');
        $sm->setOverride($session, Pc::where('name', 'PC-22')->firstOrFail(), $this->profile('Practice: AI allowed, logged'), 'accommodation');
        $sm->setOverride($session, Pc::where('name', 'PC-23')->firstOrFail(), $this->profile('Practice: AI blocked'), 'seat');
        $this->assertLessThanOrEqual(7, $this->buildQueries());

        $state = app(NetworkPolicyWriter::class)->build();
        $this->assertSame(['192.168.10.22'], $state['groups']['exempt']);
        $this->assertCount(8, $state['groups']['test']);
        $this->assertSame(['192.168.10.23'], $state['groups']['block_ai']);
    }

    /** Proxy Step 27 (I-PROXY-10): session_clients lists every session PC, also one whose profile blocks nothing. */
    public function test_session_clients_lists_every_pc_in_a_running_session(): void
    {
        Queue::fake();
        $lab = $this->bootLab();
        $this->pcs(21, 3);
        $this->assertSame([], app(NetworkPolicyWriter::class)->build()['session_clients']);   // no session

        $sm = app(SessionManager::class);
        $session = $sm->start($lab, $this->profile('Practice: AI allowed, logged'), 'CS101');
        Pc::where('name', 'PC-23')->firstOrFail()->update(['isolated' => true]);
        $state = app(NetworkPolicyWriter::class)->build();
        $this->assertSame([], $state['groups']['test']);       // nothing blocked, so in no group ...
        $this->assertSame([], $state['groups']['block_ai']);
        $this->assertSame(['192.168.10.21', '192.168.10.22'], $state['session_clients']);   // ... but in the session
        $this->assertSame(['192.168.10.23'], $state['groups']['isolated']);

        $sm->stop($session);
        $this->assertSame([], app(NetworkPolicyWriter::class)->build()['session_clients']);
    }

    public function test_effective_many_matches_effective(): void
    {
        Queue::fake();
        $lab = $this->bootLab();
        $this->pcs(21, 3);
        $svc = app(PolicyService::class);
        $session = app(SessionManager::class)->start($lab, $this->profile('Test: AI blocked'), 'CS101');
        $pc = Pc::where('name', 'PC-22')->firstOrFail();
        app(SessionManager::class)->setOverride($session, $pc, $this->profile('Practice: AI blocked'), 'seat');
        $many = $svc->effectiveMany(Pc::all());
        foreach (Pc::all() as $p) {
            $one = $svc->effective($p);
            $this->assertSame($one['profile']->id, $many[$p->id]['profile']->id);
            $this->assertSame($one['session']?->id, $many[$p->id]['session']?->id);
            $this->assertSame($one['override']?->id, $many[$p->id]['override']?->id);
        }
        $this->assertSame(LabSession::activeFor($lab->id)->id, $many[$pc->id]['session']->id);
        $this->assertNotNull($many[$pc->id]['override']);
    }

    /** Proxy Step 14 (I-PROXY-21): AI-endpoint signatures come from data/network/proxy.yaml, never from settings. */
    public function test_google_signatures_come_from_the_yaml_only(): void
    {
        $this->bootLab();
        $seed = Yaml::parseFile(config('xephyguard.data_dir').'/network/proxy.yaml');
        Setting::put('google_ai_paths', ['/not-a-setting']);   // a stray row must not override the file
        $google = app(NetworkPolicyWriter::class)->build()['google'];
        $this->assertSame($seed['google_search_hosts'], $google['search_hosts']);
        $this->assertSame($seed['google_ai_paths'], $google['ai_paths']);
        $this->assertSame($seed['search_css_hosts'], $google['css_hosts']);
        $this->assertSame(['/async/folwr'], $google['ai_paths']);
        foreach (NetworkSeed::SIGNATURE_KEYS as $key) {
            $this->assertNotContains($key, NetworkSeed::KEYS);
        }
        NetworkSeed::importSeed();   // bootstrap leaves non-setting rows alone
        $this->assertSame(['/not-a-setting'], Setting::get('google_ai_paths'));
    }

    public function test_write_is_atomic_and_mode_0640(): void
    {
        $this->bootLab();
        $path = config('xephyguard.net_state_path');
        $state = app(NetworkPolicyWriter::class)->write();
        $this->assertSame(0640, fileperms($path) & 0777);
        $this->assertSame($state['version'], json_decode((string) file_get_contents($path), true)['version']);
        $this->assertSame(['state.json'], array_values(array_diff(scandir(dirname($path)), ['.', '..'])));
        app(NetworkPolicyWriter::class)->write();   // overwrite keeps the mode, leaves no temp file
        $this->assertSame(0640, fileperms($path) & 0777);
        $this->assertSame(['state.json'], array_values(array_diff(scandir(dirname($path)), ['.', '..'])));
    }
}
