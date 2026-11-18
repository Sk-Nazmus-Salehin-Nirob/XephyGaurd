<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\AuditLog;
use Illuminate\Database\Eloquent\Model;

class Audit
{
    public static function log(string $action, ?Model $subject = null, array $details = []): AuditLog
    {
        $attrs = [
            'user_id' => auth()->id(),
            'action' => $action,
            'subject_type' => $subject ? class_basename($subject) : null,
            'subject_id' => $subject?->getKey(),
            'details' => $details ?: null,
            'ip' => request()?->ip(),
        ];

        // A failed audit write must fail the action: no unaudited changes (I-SERVER-14, DECISIONS #29).
        return AuditLog::create($attrs);
    }
}
