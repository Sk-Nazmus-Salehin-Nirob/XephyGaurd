<?php

declare(strict_types=1);

namespace App\Support;

/**
 * Hosts that may open a Reverb WebSocket (config `reverb.apps.apps.0.allowed_origins`).
 *
 * Reverb compares only the host of the `Origin` header against this list (`*` is a wildcard
 * inside a pattern). Browsers: the dashboard host from APP_URL plus any extra hosts listed in
 * REVERB_ALLOWED_ORIGINS (comma-separated hosts or origins, e.g. a DNS name staff use instead of
 * the IP). A bare `*` is never accepted. Agents send no `Origin`; nginx sets AGENT_HOST on the
 * mTLS-only `:8443 /app/` location. `.invalid` never resolves, so no web page can carry it.
 */
final class ReverbOrigins
{
    public const AGENT_HOST = 'xg-agent.invalid';

    /** @return list<string> */
    public static function resolve(?string $appUrl, ?string $extra): array
    {
        $hosts = [self::host((string) $appUrl)];
        foreach (explode(',', (string) $extra) as $item) {
            $item = trim($item);
            $hosts[] = str_contains($item, '://') ? self::host($item) : strtolower($item);
        }
        $hosts[] = self::AGENT_HOST;

        return array_values(array_unique(array_filter(
            $hosts,
            static fn (?string $h): bool => $h !== null && $h !== '' && trim($h, '*') !== '',
        )));
    }

    private static function host(string $url): ?string
    {
        $host = parse_url($url, PHP_URL_HOST);

        return is_string($host) ? strtolower($host) : null;
    }
}
