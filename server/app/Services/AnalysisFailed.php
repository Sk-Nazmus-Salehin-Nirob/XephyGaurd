<?php

declare(strict_types=1);

namespace App\Services;

use RuntimeException;
use Throwable;

/** A scoring call to the analysis service failed. `retryable` = worth trying again later
 * (service down, timeout, 5xx, 429); otherwise the request itself is wrong (token, unknown session). */
class AnalysisFailed extends RuntimeException
{
    public function __construct(string $message, public readonly bool $retryable, ?Throwable $previous = null)
    {
        parent::__construct($message, 0, $previous);
    }

    public static function transient(string $message, ?Throwable $previous = null): self
    {
        return new self($message, true, $previous);
    }

    public static function permanent(string $message): self
    {
        return new self($message, false);
    }
}
