<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('evidence_captures', function (Blueprint $table) {
            $table->id();
            $table->foreignId('pc_id')->constrained('pcs')->cascadeOnDelete();
            $table->foreignId('lab_session_id')->nullable()->constrained('lab_sessions')->nullOnDelete();
            $table->string('user', 120)->nullable();
            $table->foreignId('captured_by')->nullable()->constrained('users')->nullOnDelete();
            $table->unsignedInteger('monitor')->default(0);
            $table->string('source_mode', 24)->default('snapshot');
            $table->string('file_path', 255);
            $table->string('mime_type', 64)->default('image/png');
            $table->string('sha256', 64);
            $table->unsignedBigInteger('size_bytes');
            $table->string('note', 500)->nullable();
            $table->timestamp('occurred_at');
            $table->timestamps();

            $table->index(['pc_id', 'occurred_at']);
            $table->index(['lab_session_id', 'occurred_at']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('evidence_captures');
    }
};
