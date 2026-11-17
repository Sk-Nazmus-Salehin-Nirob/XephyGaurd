// Actor-core primitives and message flow (docs/DECISIONS.md "agent actor core").
#include <catch2/catch_test_macros.hpp>
#include <string>
#include <thread>

#include "xg/mailbox.hpp"

using namespace xg;
using namespace std::chrono_literals;

TEST_CASE("mailbox keeps FIFO order across producers and drops when full") {
    Mailbox<int> mb(1000);
    std::vector<std::thread> producers;
    for (int t = 0; t < 4; ++t)
        producers.emplace_back([&mb, t] {
            for (int i = 0; i < 200; ++i) mb.post(t * 1000 + i);
        });
    for (auto& p : producers) p.join();
    auto all = mb.take_all();
    REQUIRE(all.size() == 800);
    // Per producer, messages arrive in the order they were posted.
    for (int t = 0; t < 4; ++t) {
        int last = -1;
        for (int v : all)
            if (v / 1000 == t) {
                CHECK(v % 1000 > last);
                last = v % 1000;
            }
    }
    Mailbox<int> small(2);
    CHECK(small.post(1));
    CHECK(small.post(2));
    CHECK_FALSE(small.post(3));
    CHECK(small.dropped() == 1);
    small.close();
    CHECK_FALSE(small.post(4));
    CHECK(small.take_all().size() == 2);
}

TEST_CASE("mailbox wait returns on a message, on wake, or on timeout") {
    Mailbox<std::string> mb;
    auto t0 = std::chrono::steady_clock::now();
    CHECK(mb.wait_take_all(30ms).empty());
    CHECK(std::chrono::steady_clock::now() - t0 >= 25ms);
    std::thread th([&] {
        std::this_thread::sleep_for(20ms);
        mb.post("hi");
    });
    auto got = mb.wait_take_all(5s);
    th.join();
    REQUIRE(got.size() == 1);
    CHECK(got[0] == "hi");
    std::thread w([&] {
        std::this_thread::sleep_for(20ms);
        mb.wake();
    });
    t0 = std::chrono::steady_clock::now();
    CHECK(mb.wait_take_all(5s).empty());
    w.join();
    CHECK(std::chrono::steady_clock::now() - t0 < 4s);
}

TEST_CASE("snapshot readers keep their copy while a writer publishes") {
    Snapshot<std::vector<int>> s;
    CHECK(s.get()->empty());
    s.set({1, 2, 3});
    auto held = s.get();
    s.set({4});
    CHECK(held->size() == 3);
    CHECK(s.get()->front() == 4);
}
