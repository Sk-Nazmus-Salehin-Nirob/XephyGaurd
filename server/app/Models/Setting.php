<?php

declare(strict_types=1);

namespace App\Models;

use App\Models\Concerns\InvalidatesPolicies;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Facades\Cache;

/** Key/value settings editable in the dashboard; values fall back to config/xephyguard.php. */
class Setting extends Model
{
    use InvalidatesPolicies;

    protected $primaryKey = 'key';

    public $incrementing = false;

    protected $keyType = 'string';

    protected $fillable = ['key', 'value'];

    protected $casts = ['value' => 'json'];

    public static function get(string $key, mixed $default = null): mixed
    {
        $all = Cache::remember('xg.settings', 60, fn () => static::query()->pluck('value', 'key')->all());
        if (array_key_exists($key, $all)) {
            return $all[$key];
        }

        return $default ?? config("xephyguard.$key");
    }

    public static function put(string $key, mixed $value): void
    {
        static::query()->updateOrCreate(['key' => $key], ['value' => $value]);
        Cache::forget('xg.settings');
    }

    /** Removes a stored value, so `get` falls back to its default again. */
    public static function forget(string $key): void
    {
        static::query()->find($key)?->delete();   // model delete: fires the policy invalidation
        Cache::forget('xg.settings');
    }

    public static function set(string $key, mixed $value): void
    {
        static::put($key, $value);
    }
}
