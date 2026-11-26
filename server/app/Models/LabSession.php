<?php

declare(strict_types=1);

namespace App\Models;

use App\Models\Concerns\InvalidatesPolicies;
use Carbon\CarbonInterface;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\Collection;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\BelongsToMany;
use Illuminate\Database\Eloquent\Relations\HasMany;

/** A lab session: course + mode + profile + roster + time window. */
class LabSession extends Model
{
    use InvalidatesPolicies;

    protected $table = 'lab_sessions';

    protected $fillable = ['lab_id', 'profile_id', 'timetable_entry_id', 'course', 'title', 'mode', 'status',
        'starts_at', 'ends_at', 'started_at', 'ended_at', 'started_by', 'experiment_condition', 'experiment_group', 'network_lock'];

    /** Network lock values (proxy-only mode, DECISIONS #23). */
    public const NETWORK_LOCKS = ['off', 'observe', 'strict'];

    protected $casts = ['starts_at' => 'datetime', 'ends_at' => 'datetime', 'started_at' => 'datetime', 'ended_at' => 'datetime'];

    /** @return BelongsTo<Lab, $this> */
    public function lab(): BelongsTo
    {
        return $this->belongsTo(Lab::class);
    }

    /** @return BelongsTo<Profile, $this> */
    public function profile(): BelongsTo
    {
        return $this->belongsTo(Profile::class);
    }

    /** @return BelongsToMany<Pc, $this> */
    public function pcs(): BelongsToMany
    {
        return $this->belongsToMany(Pc::class, 'session_pcs')->withPivot(['override_profile_id', 'override_reason', 'student_id'])->withTimestamps();
    }

    /** @return HasMany<SessionPc, $this> */
    public function sessionPcs(): HasMany
    {
        return $this->hasMany(SessionPc::class);
    }

    /** @return HasMany<Alert, $this> */
    public function alerts(): HasMany
    {
        return $this->hasMany(Alert::class);
    }

    /** @return HasMany<Score, $this> */
    public function scores(): HasMany
    {
        return $this->hasMany(Score::class);
    }

    public function scopeActive(Builder $q): Builder
    {
        return $q->where('status', 'active');
    }

    public static function activeFor(int $labId): ?self
    {
        return static::query()->where('lab_id', $labId)->active()->latest('started_at')->first();
    }

    /**
     * Sessions of the lab that were running at some moment in [$from, $to]: started by $to and either still
     * active or ended after $from. Latest start first, so the first one ranAt() a moment is the one shown then.
     *
     * @return Collection<int, static>
     */
    public static function runningBetween(int $labId, CarbonInterface $from, CarbonInterface $to): Collection
    {
        return static::query()->where('lab_id', $labId)->whereNotNull('started_at')->where('started_at', '<=', $to)
            ->where(fn (Builder $q) => $q->where(fn (Builder $q) => $q->whereNull('ended_at')->active())
                ->orWhere('ended_at', '>', $from))
            ->orderByDesc('started_at')->orderByDesc('id')->get();
    }

    /** True when the session was running at $at (started at or before it, not yet ended). */
    public function ranAt(CarbonInterface $at): bool
    {
        if ($this->started_at === null || $this->started_at->greaterThan($at)) {
            return false;
        }

        return $this->ended_at === null ? $this->status === 'active' : $this->ended_at->greaterThan($at);
    }
}
