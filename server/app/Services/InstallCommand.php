<?php

declare(strict_types=1);

namespace App\Services;

/**
 * The Linux agent install command shown on /downloads and /enroll (Step 25, S-74).
 *
 * Trust starts from the CA fingerprint the operator copies from this page (or the CCC console), not from the network:
 * the command fetches ca.crt over plain HTTP, stops unless its SHA-256 matches that fingerprint, then fetches the
 * install script over HTTPS verified against that CA and passes the same fingerprint as the pin.
 */
final class InstallCommand
{
    public const KEY_PLACEHOLDER = '<ENROLL_KEY>';

    /** @param  string  $fingerprint  lowercase hex SHA-256 of the lab CA; '' when the CA does not exist yet */
    public static function linux(string $host, string $fingerprint, string $key = self::KEY_PLACEHOLDER): string
    {
        if ($fingerprint === '') {
            return '# The lab CA does not exist yet: finish the setup wizard first.';
        }

        return 'curl -fsSL -o xg-ca.crt http://'.$host.'/ca.crt && \\'."\n"
            .'  { openssl x509 -in xg-ca.crt -noout -fingerprint -sha256 | cut -d= -f2 | tr -d : | tr A-F a-f | grep -qx '.$fingerprint
            .' || { echo "CA fingerprint mismatch: stop" >&2; false; }; } && \\'."\n"
            .'  curl -fsSL --cacert xg-ca.crt https://'.$host.'/install/linux.sh | sudo bash -s -- --key '.$key
            .' --ca-fingerprint '.$fingerprint;
    }
}
