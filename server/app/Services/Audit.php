<?php

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
        try {
            return AuditLog::create($attrs);
        } catch (\Throwable) {
            return new AuditLog($attrs);
        }
    }
}
