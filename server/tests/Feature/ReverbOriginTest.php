<?php

declare(strict_types=1);

namespace Tests\Feature;

use App\Support\ReverbOrigins;
use Laravel\Reverb\Application;
use Laravel\Reverb\Contracts\Connection;
use Laravel\Reverb\Protocols\Pusher\Exceptions\InvalidOrigin;
use Laravel\Reverb\Protocols\Pusher\Server;
use ReflectionClass;
use ReflectionMethod;
use Tests\TestCase;

/** S-51 (I-SERVER-42): Reverb accepts only the dashboard host and the nginx agent marker. */
class ReverbOriginTest extends TestCase
{
    public function test_config_has_no_wildcard_and_names_dashboard_and_agent_hosts(): void
    {
        $origins = config('reverb.apps.apps.0.allowed_origins');
        $dashboard = parse_url((string) config('app.url'), PHP_URL_HOST);

        $this->assertNotContains('*', $origins);
        $this->assertContains(strtolower($dashboard), $origins);
        $this->assertContains(ReverbOrigins::AGENT_HOST, $origins);
    }

    public function test_reverb_refuses_foreign_and_missing_origins(): void
    {
        $origins = ReverbOrigins::resolve('https://10.0.0.5', null);

        $this->assertTrue($this->accepted($origins, 'https://10.0.0.5'));
        $this->assertTrue($this->accepted($origins, 'https://10.0.0.5:443'));
        $this->assertTrue($this->accepted($origins, 'https://xg-agent.invalid'));

        $this->assertFalse($this->accepted($origins, 'https://evil.example'));
        $this->assertFalse($this->accepted($origins, 'https://10.0.0.5.evil.example'));
        $this->assertFalse($this->accepted($origins, 'https://x10.0.0.5'));
        // An agent reaching Reverb without nginx (no Origin) is refused: the marker comes only from :8443.
        $this->assertFalse($this->accepted($origins, null));
    }

    public function test_extra_origins_are_parsed_and_a_bare_wildcard_is_dropped(): void
    {
        $this->assertSame(
            ['ccc.lab.example', 'dash.example', '*.lab.example', ReverbOrigins::AGENT_HOST],
            ReverbOrigins::resolve('https://CCC.lab.example:443', ' https://Dash.Example:8443 , *, *.lab.example,, ** '),
        );
        $this->assertSame([ReverbOrigins::AGENT_HOST], ReverbOrigins::resolve('', '*'));
        $this->assertTrue($this->accepted(ReverbOrigins::resolve('', '*.lab.example'), 'https://pc1.lab.example'));
    }

    /** Runs Reverb's own Origin check (Pusher Server::verifyOrigin) against a list. */
    private function accepted(array $origins, ?string $origin): bool
    {
        $app = new Application('xephyguard', 'key', 'secret', 60, 30, $origins, 10_000);
        $connection = new class($app, $origin) extends Connection
        {
            public function __construct(Application $app, ?string $origin)
            {
                $this->application = $app;
                $this->origin = $origin;
            }

            public function identifier(): string
            {
                return '1';
            }

            public function id(): string
            {
                return '1';
            }

            public function send(string $message): void {}

            public function control(string $type = 'ping'): void {}

            public function terminate(): void {}
        };

        $server = (new ReflectionClass(Server::class))->newInstanceWithoutConstructor();
        try {
            (new ReflectionMethod(Server::class, 'verifyOrigin'))->invoke($server, $connection);

            return true;
        } catch (InvalidOrigin) {
            return false;
        }
    }
}
