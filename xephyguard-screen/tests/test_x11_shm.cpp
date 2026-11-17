#include "doctest.h"
#if defined(__linux__)
#include "x11_capture.h"
#include <cstdlib>
#include <sys/shm.h>

// Needs an X server ($DISPLAY, e.g. Xvfb); skipped without one.
TEST_CASE("X11 capture: shared memory is owner-only and marked for removal after attach") {
  if (!std::getenv("DISPLAY")) {
    MESSAGE("DISPLAY not set; skipped");
    return;
  }
  xg::X11Capture cap;
  if (!cap.initialize()) {
    MESSAGE("X11 capture not available on this display; skipped");
    return;
  }
  const int id = cap.shm_segment_id();
  REQUIRE(id >= 0);
  shmid_ds ds{};
  REQUIRE(shmctl(id, IPC_STAT, &ds) == 0);
  CHECK((ds.shm_perm.mode & 0777) == 0600);
  CHECK((ds.shm_perm.mode & SHM_DEST) != 0);  // IPC_RMID done: gone once detached
  cap.stop();
}
#endif
