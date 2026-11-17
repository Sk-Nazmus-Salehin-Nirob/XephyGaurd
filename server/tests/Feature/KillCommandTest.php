<?php

namespace Tests\Feature;

use App\Models\Command;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\Concerns\BuildsLab;
use Tests\TestCase;

/** F35: the kill command carries the process start time so the agent never hits a reused pid. */
class KillCommandTest extends TestCase
{
    use BuildsLab, RefreshDatabase;

    public function test_kill_by_pid_forwards_start_time_and_exe_kill_does_not(): void
    {
        $this->bootLab();
        [$pc] = $this->enrolledPc();
        $this->actingAs($this->user('assistant'));

        $this->postJson("/pcs/{$pc->id}/kill", ['pid' => 77, 'start_time' => 123456])->assertOk();
        $this->postJson("/pcs/{$pc->id}/kill", ['exe' => 'cursor', 'start_time' => 99])->assertOk();
        $this->postJson("/pcs/{$pc->id}/kill", ['pid' => 77, 'start_time' => 'x'])->assertStatus(422);

        $args = Command::where('type', 'kill')->orderBy('id')->pluck('args')->all();
        $this->assertSame(['pid' => 77, 'start_time' => 123456], $args[0]);
        $this->assertSame(['exe' => 'cursor'], $args[1]);  // start_time only makes sense with a pid
    }
}
