<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\Setting;
use Symfony\Component\Yaml\Yaml;

/**
 * Proxy lists seeded from data/network/proxy.yaml (S-53, I-SERVER-36): `inspect_hosts` and
 * `google_hide_selectors`. A setting overrides the seed only when an admin saved a different, non-empty
 * list; otherwise the file is the value, so shipped updates reach unedited CCCs (like unedited rules).
 */
final class NetworkSeed
{
    public const KEYS = ['inspect_hosts', 'google_hide_selectors'];

    /** @var array<string, array<string, list<string>>> parsed seed per file path */
    private static array $cache = [];

    /** @return list<string> the list from data/network/proxy.yaml ([] if the file or key is missing) */
    public static function defaults(string $key): array
    {
        $path = config('xephyguard.data_dir').'/network/proxy.yaml';
        if (! isset(self::$cache[$path])) {
            $doc = is_file($path) ? (Yaml::parseFile($path) ?? []) : [];
            self::$cache[$path] = [];
            foreach (self::KEYS as $k) {
                self::$cache[$path][$k] = self::clean($doc[$k] ?? []);
            }
        }

        return self::$cache[$path][$key] ?? [];
    }

    /** @return list<string> the admin's saved list, or the seed */
    public static function get(string $key): array
    {
        $saved = self::clean(Setting::get($key) ?? []);

        return $saved !== [] ? $saved : self::defaults($key);
    }

    /** Stores an admin's list; an empty list or one equal to the seed removes the override. */
    public static function save(string $key, array $lines): void
    {
        $lines = self::clean($lines);
        if ($lines === [] || $lines === self::defaults($key)) {
            Setting::forget($key);
        } else {
            Setting::put($key, $lines);
        }
    }

    /** Bootstrap: drops stored copies that are empty or equal to the seed, so they follow data/ again. */
    public static function importSeed(): int
    {
        $n = 0;
        foreach (self::KEYS as $key) {
            $stored = Setting::get($key);
            if ($stored === null) {
                continue;
            }
            $clean = self::clean($stored);
            if ($clean === [] || $clean === self::defaults($key)) {
                Setting::forget($key);
                $n++;
            }
        }

        return $n;
    }

    /** @return list<string> trimmed, non-empty, unique strings in their order */
    private static function clean(mixed $list): array
    {
        if (! is_array($list)) {
            return [];
        }
        $out = [];
        foreach ($list as $v) {
            if (is_string($v) && ($v = trim($v)) !== '' && ! in_array($v, $out, true)) {
                $out[] = $v;
            }
        }

        return $out;
    }
}
