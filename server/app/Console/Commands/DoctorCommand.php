<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Services\HealthChecks;
use Illuminate\Console\Command;
use Symfony\Component\Console\Formatter\OutputFormatter;

/** CLI view of HealthChecks; the Health page (AdminController::health) shows the same rows. */
class DoctorCommand extends Command
{
    protected $signature = 'xephyguard:doctor {--json}';

    protected $description = 'Check the CCC and explain problems in plain language';

    public function handle(HealthChecks $d): int
    {
        $res = $d->run();
        if ($this->option('json')) {
            $this->line(json_encode($res, JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR));
        } else {
            foreach ($res as $r) {
                $mark = $r['ok'] ? '<info>✔</info>' : ($r['level'] === 'error' ? '<error>✘</error>' : '<comment>!</comment>');
                $this->line("$mark {$r['check']}: ".OutputFormatter::escape($r['detail']));
                if (! $r['ok'] && $r['fix']) {
                    $this->line('    → '.OutputFormatter::escape($r['fix']));
                }
            }
        }

        return collect($res)->contains(fn ($r) => $r['level'] === 'error') ? self::FAILURE : self::SUCCESS;
    }
}
