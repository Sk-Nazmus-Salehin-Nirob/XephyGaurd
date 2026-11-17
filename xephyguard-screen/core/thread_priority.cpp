#include "thread_priority.h"

#if defined(_WIN32)
#include <windows.h>
#else
#include <pthread.h>
#include <sched.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <unistd.h>
#endif

namespace xg {

bool set_current_thread_idle_priority() {
#if defined(_WIN32)
  // Background mode also lowers the thread's I/O and memory priority. (compile-checked only)
  if (SetThreadPriority(GetCurrentThread(), THREAD_MODE_BACKGROUND_BEGIN)) return true;
  return SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL) != 0;
#elif defined(__linux__)
  sched_param sp{};
  sp.sched_priority = 0;
  if (pthread_setschedparam(pthread_self(), SCHED_IDLE, &sp) == 0) return true;
  // On Linux setpriority with a thread id changes that thread only.
  const auto tid = static_cast<id_t>(::syscall(SYS_gettid));
  return ::setpriority(PRIO_PROCESS, tid, 19) == 0;
#else
  return ::setpriority(PRIO_PROCESS, 0, 19) == 0;
#endif
}

}  // namespace xg
