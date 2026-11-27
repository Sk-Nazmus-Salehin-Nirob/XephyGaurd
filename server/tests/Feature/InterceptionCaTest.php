<?php

declare(strict_types=1);

namespace Tests\Feature;

use App\Services\CertificateAuthority;
use App\Services\PolicyService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\Concerns\BuildsLab;
use Tests\TestCase;

/** S-75: the proxy's own interception CA is published to agents (mTLS policy) and on /interception-ca.crt. */
class InterceptionCaTest extends TestCase
{
    use BuildsLab, RefreshDatabase;

    /** A self-signed CA like the one ccc-deploy install.sh creates for mitmproxy. */
    private function writeInterceptionCa(): string
    {
        $ca = app(CertificateAuthority::class);
        $conf = $ca->opensslConfig();
        $key = openssl_pkey_new(['private_key_type' => OPENSSL_KEYTYPE_EC, 'curve_name' => 'prime256v1', 'config' => $conf]);
        $csr = openssl_csr_new(['commonName' => 'XephyGuard Interception CA'], $key, ['digest_alg' => 'sha256', 'config' => $conf]);
        $cert = openssl_csr_sign($csr, null, $key, 30, ['digest_alg' => 'sha256', 'config' => $conf, 'x509_extensions' => 'v3_ca']);
        @unlink($conf);
        openssl_x509_export($cert, $pem);
        file_put_contents($ca->interceptionCertPath(), $pem);

        return $pem;
    }

    public function test_nothing_is_published_while_there_is_no_interception_ca(): void
    {
        $this->bootLab();
        [$pc, $token, $cert] = $this->enrolledPc();

        $this->get('/interception-ca.crt')->assertNotFound();
        $this->assertArrayNotHasKey('interception_ca_sha256', app(PolicyService::class)->forPc($pc));
        $this->withHeaders($this->agentHeaders($token, $cert))->getJson('/api/agent/v1/policy')->assertOk()
            ->assertJsonPath('interception_ca', null)
            ->assertJsonMissingPath('policy.interception_ca_sha256');
        $this->get('/downloads')->assertOk()->assertDontSee('Proxy interception CA');
    }

    public function test_the_interception_ca_reaches_the_policy_the_route_and_downloads(): void
    {
        $this->bootLab();
        [$pc, $token, $cert] = $this->enrolledPc();
        $svc = app(PolicyService::class);
        $before = $svc->forPc($pc);   // cached without the CA

        $pem = $this->writeInterceptionCa();
        $sha = openssl_x509_fingerprint($pem, 'sha256');

        $after = $svc->forPc($pc);   // the file is part of the cache stamp, so no stale policy
        $this->assertSame($sha, $after['interception_ca_sha256']);
        $this->assertNotSame($before['version'], $after['version']);
        $this->withHeaders($this->agentHeaders($token, $cert))->getJson('/api/agent/v1/policy')->assertOk()
            ->assertJsonPath('policy.interception_ca_sha256', $sha)
            ->assertJsonPath('interception_ca', $pem);
        $res = $this->get('/interception-ca.crt')->assertOk()->assertHeader('Content-Type', 'application/x-pem-file');
        $this->assertSame($pem, $res->getContent());
        $this->get('/downloads')->assertOk()->assertSee($sha);
        $this->assertNotSame(app(CertificateAuthority::class)->fingerprint(), $sha);
    }

    public function test_a_file_that_is_not_a_ca_certificate_counts_as_none(): void
    {
        $this->bootLab();
        [$pc, , $cert] = $this->enrolledPc();
        $ca = app(CertificateAuthority::class);

        file_put_contents($ca->interceptionCertPath(), $cert);   // an agent client cert: CA:false
        $this->assertNull($ca->interceptionCertPem());
        $this->get('/interception-ca.crt')->assertNotFound();
        file_put_contents($ca->interceptionCertPath(), "not a certificate\n");
        $this->assertNull($ca->interceptionFingerprint());
        $this->assertArrayNotHasKey('interception_ca_sha256', app(PolicyService::class)->forPc($pc));
    }
}
