<?php

declare(strict_types=1);

namespace App\Services;

use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;

/** Talks to the Python analysis service (analysis/), which reads the session data from MySQL,
 * computes v1 (and optionally v2) scores, writes the `scores` table and returns a summary.
 * Authenticates with its own `XG_ANALYSIS_TOKEN`, never the internal token the proxy holds (I-ANALYSIS-17). */
class AnalysisClient
{
    /** Seconds for one scoring call; ScoreSession::$timeout must stay above it. */
    public const TIMEOUT_S = 75;

    public const MIN_TOKEN_LENGTH = 16;

    /** @throws AnalysisFailed */
    public function scoreSession(int $sessionId): array
    {
        $token = self::token();
        try {
            $response = Http::timeout(self::TIMEOUT_S)->connectTimeout(5)->acceptJson()->withToken($token)
                ->post($this->url('/score'), ['session_id' => $sessionId]);
        } catch (ConnectionException $e) {
            throw AnalysisFailed::transient('analysis service unreachable: '.mb_substr($e->getMessage(), 0, 200), $e);
        }

        $status = $response->status();
        if ($response->serverError() || $status === 429) {
            throw AnalysisFailed::transient("analysis service answered HTTP {$status}");
        }
        if (! $response->successful()) {
            $error = $response->json('error');

            throw AnalysisFailed::permanent("analysis service refused the request (HTTP {$status})"
                .(is_string($error) ? ': '.mb_substr($error, 0, 200) : ''));
        }
        $json = $response->json();
        if (! is_array($json)) {
            throw AnalysisFailed::transient('analysis service sent no JSON object');
        }

        return $json;
    }

    /** The scoring token; refused when unset, short, or equal to the internal token. @throws AnalysisFailed */
    public static function token(): string
    {
        $token = trim((string) config('xephyguard.analysis_token'));
        if ($token === '') {
            throw AnalysisFailed::permanent('XG_ANALYSIS_TOKEN is not set');
        }
        if (strlen($token) < self::MIN_TOKEN_LENGTH) {
            throw AnalysisFailed::permanent('XG_ANALYSIS_TOKEN is shorter than '.self::MIN_TOKEN_LENGTH.' characters');
        }
        if (hash_equals(trim((string) config('xephyguard.internal_token')), $token)) {
            throw AnalysisFailed::permanent('XG_ANALYSIS_TOKEN must differ from XG_INTERNAL_TOKEN');
        }

        return $token;
    }

    public function health(): bool
    {
        try {
            return Http::timeout(3)->get($this->url('/health'))->ok();
        } catch (\Throwable) {
            return false;
        }
    }

    private function url(string $path): string
    {
        return rtrim((string) config('xephyguard.analysis_url'), '/').$path;
    }
}
