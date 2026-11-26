<?php

declare(strict_types=1);

namespace App\Models;

use App\Models\Concerns\InvalidatesPolicies;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class SessionPc extends Model
{
    use InvalidatesPolicies;

    protected $table = 'session_pcs';

    protected $fillable = ['lab_session_id', 'pc_id', 'override_profile_id', 'override_reason', 'student_id'];

    /** @return BelongsTo<LabSession, $this> */
    public function session(): BelongsTo
    {
        return $this->belongsTo(LabSession::class, 'lab_session_id');
    }

    /** @return BelongsTo<Pc, $this> */
    public function pc(): BelongsTo
    {
        return $this->belongsTo(Pc::class);
    }

    /** @return BelongsTo<Student, $this> */
    public function student(): BelongsTo
    {
        return $this->belongsTo(Student::class);
    }

    /** @return BelongsTo<Profile, $this> */
    public function overrideProfile(): BelongsTo
    {
        return $this->belongsTo(Profile::class, 'override_profile_id');
    }
}
