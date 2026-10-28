#!/usr/bin/env python3
"""Generate the midterm explanation PDF with all images embedded."""
import os
from fpdf import FPDF

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "..", "..")  # D:\System_Design\Assignments
IMG = lambda n: os.path.join(IMAGES_DIR, f"midterm-{n}.png")
OUTPUT = os.path.join(os.path.dirname(__file__), "EXPLANATION.pdf")


class PDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(128)
            self.cell(0, 5, "INFO 7375 Midterm - Option C: Redis/ElastiCache Virtual Waiting Room", align="R")
            self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(0, 51, 102)
        self.ln(4)
        self.cell(0, 10, title)
        self.ln(12)

    def sub_title(self, title):
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(0, 70, 130)
        self.ln(2)
        self.cell(0, 8, title)
        self.ln(10)

    def sub_sub_title(self, title):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(50, 50, 50)
        self.ln(2)
        self.cell(0, 7, title)
        self.ln(8)

    def body_text(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 5.5, text)
        self.ln(2)

    def bold_text(self, text):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 5.5, text)
        self.ln(2)

    def code_block(self, text):
        self.set_font("Courier", "", 8)
        self.set_fill_color(240, 240, 240)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 4.5, text, fill=True)
        self.ln(3)

    def add_image_full(self, path, caption=""):
        if not os.path.exists(path):
            self.body_text(f"[Image not found: {path}]")
            return
        avail_w = self.w - self.l_margin - self.r_margin
        # Check if we need a new page (estimate image height)
        if self.get_y() > self.h - 80:
            self.add_page()
        self.image(path, x=self.l_margin, w=avail_w)
        if caption:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(100)
            self.cell(0, 5, caption, align="C")
            self.ln(6)
        self.ln(3)

    def table_row(self, cells, widths, bold=False, fill=False):
        self.set_font("Helvetica", "B" if bold else "", 9)
        if fill:
            self.set_fill_color(220, 230, 241)
        h = 6
        for i, (cell, w) in enumerate(zip(cells, widths)):
            self.cell(w, h, str(cell), border=1, fill=fill)
        self.ln(h)


def build_pdf():
    pdf = PDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title page
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(0, 51, 102)
    pdf.ln(30)
    pdf.cell(0, 15, "INFO 7375 Systems Design", align="C")
    pdf.ln(18)
    pdf.cell(0, 15, "Midterm: Virtual Waiting Room", align="C")
    pdf.ln(18)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(180, 50, 50)
    pdf.cell(0, 12, "Option C: Redis / ElastiCache", align="C")
    pdf.ln(20)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, "Difficulty Coefficient: 1.08", align="C")
    pdf.ln(10)
    pdf.cell(0, 8, "27 October 2026", align="C")
    pdf.ln(30)

    # =========================================================================
    pdf.add_page()
    pdf.section_title("1. Design Overview")

    pdf.sub_title("The Problem")
    pdf.body_text(
        "The Week 5 event-driven order system has no admission control. When 1,520 visitors arrive in 25 seconds "
        "and the backend is capped at 40 requests/second, approximately 41% of fans (624 out of 1,520) are randomly "
        "rejected with HTTP 429 errors. There is no fairness, no ordering, and bots have the same chance of getting "
        "through as real fans."
    )
    pdf.body_text("The baseline stampede run shows the problem clearly:")
    pdf.add_image_full(IMG(13), "Figure 1: Baseline stampede -- 624 throttled, peak 65 orders/sec")

    pdf.body_text("The baseline dashboard confirms the damage -- a spike of 593 4xx errors at the API Gateway level:")
    pdf.add_image_full(IMG(1), "Figure 2: Baseline dashboard -- API Gateway errors, Lambda concurrency, invocations")
    pdf.add_image_full(IMG(2), "Figure 3: Baseline dashboard -- Queue depths, message age, DLQ, Lambda duration")

    pdf.sub_title("Our Solution: A Redis-Based Virtual Waiting Room")
    pdf.body_text(
        "We chose Option C (Redis/ElastiCache) to implement a virtual waiting room that sits in front of POST /orders. "
        "The waiting room uses Redis's atomic INCR command to assign each visitor a sequential queue position, then uses "
        "a time-based computation to determine when each visitor's turn has come. This is the same architectural pattern "
        "used by SeatGeek and the AWS reference architecture for virtual waiting rooms."
    )

    pdf.sub_title("Why Option C (Redis) Over the Other Options")
    pdf.body_text(
        "Redis was chosen for one specific technical reason: its INCR command can handle over 100,000 atomic increments "
        "per second on a single key with sub-millisecond latency. In contrast, DynamoDB's atomic increment on a single "
        "item (Option A) creates a \"hot partition\" -- at high concurrency, all writes to one item contend on the same "
        "physical storage partition, causing throttling. For a waiting room counter that every single visitor hits, Redis "
        "is the right tool because the workload is pure atomic coordination, not data storage."
    )
    pdf.body_text(
        "This is also why the real-world implementations (AWS's own reference architecture and SeatGeek's \"Bouncer\" "
        "service) use Redis, not DynamoDB, for this exact use case."
    )

    # =========================================================================
    pdf.add_page()
    pdf.section_title("2. Architecture")

    pdf.sub_title("What Changed From the Baseline")
    pdf.body_text(
        "The baseline Week 5 architecture is completely unchanged. We added a waiting room layer in front of the existing "
        "system. The existing pipeline (OrderProducer -> SNS -> SQS -> three consumers) only ever sees the admitted traffic "
        "rate (~10 orders/sec), never the raw stampede (100 arrivals/sec)."
    )

    pdf.sub_title("Architecture Diagram")
    pdf.code_block(
        "                +------------------------------------------+\n"
        "                |         WAITING ROOM (new)                |\n"
        "                |                                           |\n"
        "  Fan --------> |  POST /waiting-room/join                  |\n"
        "                |    -> JoinQueue Lambda (VPC)              |\n"
        "                |    -> Redis INCR (atomic position)        |\n"
        "                |                                           |\n"
        "  Fan polls --> |  GET /waiting-room/status/{visitor_id}    |\n"
        "                |    -> StatusCheck Lambda (VPC)            |\n"
        "                |    -> Computes: position <= elapsed*rate? |\n"
        "                |    -> If yes: writes admission to DynamoDB|\n"
        "                +------------------+-----------------------+\n"
        "                                   |\n"
        "                      only ~10/sec reach here\n"
        "                                   v\n"
        "  Bot -------> POST /orders  -->  Gate (DynamoDB conditional update)\n"
        "  (no token)                      Bot: 403 | Fan: order proceeds\n"
        "                                   v\n"
        "               OrderProducer -> SNS -> SQS -> 3 consumers (unchanged)"
    )

    pdf.body_text("The successful deployment with the waiting room and all its resources:")
    pdf.add_image_full(IMG(3), "Figure 4: CDK deploy output -- 541s total, VPC + ElastiCache + Lambdas created")

    pdf.sub_title("AWS Resources Created")
    w = [45, 55, 55, 30]
    pdf.table_row(["Resource", "Type", "Purpose", "Cost"], w, bold=True, fill=True)
    pdf.table_row(["VPC", "EC2 VPC, 2 subnets", "Network isolation for Redis", "$0"], w)
    pdf.table_row(["DDB Endpoint", "Gateway VPC Endpoint", "Free path to DynamoDB", "$0"], w)
    pdf.table_row(["Security Group", "EC2 SG", "Lambda-Redis port 6379", "$0"], w)
    pdf.table_row(["ElastiCache", "cache.t4g.micro x1", "Atomic INCR counters", "$0.41/day"], w)
    pdf.table_row(["Admissions Table", "DynamoDB on-demand", "Gate verifies tokens", "~$0"], w)
    pdf.table_row(["JoinQueue", "Lambda (VPC)", "POST /waiting-room/join", "per-invoke"], w)
    pdf.table_row(["StatusCheck", "Lambda (VPC)", "GET /waiting-room/status", "per-invoke"], w)
    pdf.ln(3)

    pdf.bold_text("Total idle cost: $0.77/day (ElastiCache $0.41 + Kinesis $0.36). Well under the $1/day limit.")

    pdf.sub_title("Critical Networking Decision: No NAT Gateway")
    pdf.body_text(
        "NAT Gateways cost $32-98/month. Our design avoids one entirely:\n\n"
        "- JoinQueue and StatusCheck Lambda are inside the VPC (to reach Redis).\n"
        "- They reach DynamoDB via a free Gateway VPC Endpoint ($0/hour, $0/GB).\n"
        "- OrderProducer stays outside the VPC entirely -- it doesn't need Redis.\n\n"
        "If we had naively put OrderProducer inside the VPC, it would need a NAT Gateway to reach SNS "
        "(a public service), adding $32+/month. Correct service-boundary design saved us that entirely."
    )

    # =========================================================================
    pdf.add_page()
    pdf.section_title("3. How the Waiting Room Works")

    pdf.sub_title("Step 1: A Fan Joins the Line (POST /waiting-room/join)")
    pdf.body_text(
        "When a fan joins, the JoinQueue Lambda executes an atomic Lua script on Redis:"
    )
    pdf.code_block(
        "-- If more than 60 seconds since the last join, reset (new run)\n"
        "local last = tonumber(redis.call('GET', KEYS[3]) or '0')\n"
        "local now  = tonumber(ARGV[1])\n"
        "if (now - last) > 60 then\n"
        "    redis.call('SET', KEYS[1], 0)      -- reset position counter\n"
        "    redis.call('DEL', KEYS[2])          -- delete start_time\n"
        "end\n"
        "redis.call('SET', KEYS[3], ARGV[1])     -- update last_join_time\n"
        "local pos = redis.call('INCR', KEYS[1]) -- assign next position\n"
        "if pos == 1 then\n"
        "    redis.call('SET', KEYS[2], ARGV[1]) -- first visitor sets start_time\n"
        "end\n"
        "return pos"
    )
    pdf.body_text(
        "Why a Lua script? Redis executes Lua scripts atomically (single-threaded, no interruption). When 100 visitors "
        "join per second, every single one gets a unique, sequential position number with zero possibility of collision. "
        "The gap detection (resetting after 60 seconds of inactivity) is also atomic -- two concurrent \"first visitors "
        "of a new run\" can't both detect the gap and race to reset."
    )
    pdf.body_text("The Lambda stores visitor metadata in a Redis hash and calls telemetry.joined().")

    pdf.sub_title("Step 2: A Fan Polls for Status (GET /waiting-room/status/{id})")
    pdf.body_text(
        "The StatusCheck Lambda:\n"
        "1. Validates the visitor_id (must be UUID, else 400).\n"
        "2. Checks DynamoDB first -- if already admitted, return the existing token (idempotent) or order_placed:true.\n"
        "3. Looks up the visitor's position and joined_at from Redis.\n"
        "4. Computes: max_admitted = int(elapsed * ADMIT_PER_SECOND).\n"
        "5. If position <= max_admitted: writes admission record to DynamoDB with ConditionExpression to prevent "
        "double-admission, emits telemetry.admitted() and telemetry.time_in_line(seconds).\n"
        "6. If position > max_admitted: returns {\"status\": \"waiting\"}."
    )
    pdf.body_text(
        "The ConditionExpression=\"attribute_not_exists(visitor_id)\" prevents double-admission if two concurrent polls "
        "both try to write. Exactly one wins; the other catches ConditionalCheckFailedException and reads the existing record."
    )

    pdf.sub_title("Step 3: Fan Places an Order / Bots Get Rejected")
    pdf.body_text(
        "The fan sends POST /orders with X-Visitor-Id and X-Admission-Token headers. The gate (provided, unmodified) "
        "does a single atomic DynamoDB conditional update: exists? token matches? used=false? not expired? If all pass: "
        "used=true, order proceeds. If any fail: 403.\n\n"
        "Bots skip the waiting room and go straight to POST /orders with no headers. The gate returns 403 immediately."
    )

    pdf.sub_title("Why No AdvanceServingCounter Lambda")
    pdf.body_text(
        "Instead of a separate Lambda + EventBridge rule incrementing a serving_counter, we compute admission from "
        "elapsed time: max_admitted = elapsed * rate. This eliminates an entire Lambda and EventBridge rule, provides "
        "perfectly smooth admission (not chunked by a timer), and achieves 100% rate accuracy (measured 9.96/s vs "
        "configured 10/s)."
    )

    pdf.sub_title("The Gap Detection Problem and Solution")
    pdf.body_text(
        "During development, we discovered Redis retains state between runs. A rehearsal sets wr:start_time, and if the "
        "stampede starts 2 minutes later, elapsed=120s means max_admitted=1200 -- all fans admitted instantly, causing "
        "429 errors. The Lua script's gap detection (reset after 60 seconds of inactivity) fixes this atomically."
    )

    # =========================================================================
    pdf.add_page()
    pdf.section_title("4. Tests")

    pdf.body_text("We wrote 13 tests organized into three categories:")

    pdf.sub_title("Join Tests (4 tests)")
    pdf.body_text(
        "- test_returns_202_with_required_fields -- validates HTTP contract: 202, UUID visitor_id, poll_interval, poll_path\n"
        "- test_sequential_positions -- 5 joins get positions [1, 2, 3, 4, 5]\n"
        "- test_unique_visitor_ids -- 10 joins produce 10 distinct UUIDs\n"
        "- test_concurrent_joins_get_different_positions -- 5 simultaneous joins (ThreadPoolExecutor) each get unique positions"
    )

    pdf.sub_title("Status Tests (7 tests)")
    pdf.body_text(
        "- test_malformed_id_returns_400 -- \"not-a-uuid\" returns 400\n"
        "- test_unknown_visitor_returns_400 -- UUID that never joined returns 400\n"
        "- test_waiting_when_not_yet_admitted -- position 100 with minimal elapsed returns \"waiting\"\n"
        "- test_admitted_when_turn_comes -- position 1 with 10s elapsed returns \"admitted\" with UUID token\n"
        "- test_admission_record_matches_gate_contract -- DynamoDB record has all 5 required fields\n"
        "- test_re_poll_returns_same_token -- polling twice returns the same token (idempotent)\n"
        "- test_token_hidden_after_use -- after gate sets used=true, status returns order_placed:true without token"
    )

    pdf.sub_title("Concurrency Tests (2 tests)")
    pdf.body_text(
        "- test_concurrent_status_polls_same_visitor -- two simultaneous polls return the same token\n"
        "- test_fifo_ordering -- with 5 visitors and time for 3 admissions, exactly positions 1-3 are admitted"
    )
    pdf.body_text(
        "All tests use moto for DynamoDB mocking and a custom FakeRedis class implementing INCR, GET, SET, HSET, "
        "HGETALL, EXPIRE, and EVAL. The FakeRedis.eval() reproduces the Lua script's logic in Python."
    )

    # =========================================================================
    pdf.add_page()
    pdf.section_title("5. Telemetry and Dashboard")

    pdf.sub_title("Three Standard Metrics")
    pdf.body_text(
        "1. telemetry.joined() -- called once per visitor in join_handler.py after Redis position is assigned\n"
        "2. telemetry.admitted() -- called once per visitor in status_handler.py when admission record is written\n"
        "3. telemetry.time_in_line(seconds) -- called at admission with time.time() - joined_at\n\n"
        "These use CloudWatch Embedded Metric Format (EMF): each call prints a JSON line to stdout, which CloudWatch "
        "Logs extracts into metrics automatically. No API calls, no extra permissions needed."
    )

    pdf.sub_title("Three Custom Dashboard Widgets")
    pdf.add_image_full(IMG(12), "Figure 5: Custom widgets -- Redis connections/commands, Redis CPU, Admissions writes")
    pdf.body_text(
        "1. Redis - connections & commands/s: CurrConnections peaked at ~102 as Lambda scaled out. "
        "SetTypeCmds/GetTypeCmds peaked at ~19K commands/min.\n\n"
        "2. Redis - CPU utilization: Engine CPU peaked at ~6.5%, host CPU at ~3.4%. The cache.t4g.micro has "
        "plenty of headroom -- nowhere near saturation.\n\n"
        "3. Admissions table - writes: DynamoDB WCU consumed. The initial spike (~1.6K) is from the rehearsal, "
        "followed by the stampede's steady ~803 WCU as admissions flow at the configured rate."
    )

    pdf.sub_title("Full Dashboard During the Stampede")
    pdf.body_text("Row 1: Front door and Lambda scaling")
    pdf.add_image_full(IMG(8), "Figure 6: API Gateway errors, Lambda concurrency, Lambda invocations")
    pdf.body_text(
        "The 4xx spike at ~20:25 is from the baseline run (624 throttled). During the waiting room run (~20:39-20:42), "
        "4xx is near zero -- only 78 bot rejections (403s), which are correct behavior."
    )

    pdf.body_text("Row 2: Queues and consumer health")
    pdf.add_image_full(IMG(9), "Figure 7: Queue depths, oldest message age, DLQ depths, errors/throttles, duration, time in line")
    pdf.body_text(
        "Queue depths stay at zero -- the waiting room throttles inflow to ~10/sec. DLQ depths are zero. "
        "Lambda errors and throttles are zero across all functions."
    )

    pdf.body_text("Row 3: Time in line (zoomed)")
    pdf.add_image_full(IMG(10), "Figure 8: Lambda errors/throttles (zero), Lambda duration p99, Time in line median and p95")
    pdf.body_text(
        "The time-in-line panel shows the admission pacing: median climbs steadily from ~2s to ~2.1 min as later "
        "visitors wait. This linear climb is exactly what a constant-rate admission produces."
    )

    pdf.body_text("Row 4: The waiting room's own metrics")
    pdf.add_image_full(IMG(11), "Figure 9: Visitors joined/admitted per minute, People waiting now, API Gateway request count")
    pdf.body_text(
        "~1,440 visitors join in one burst (blue spike), then admissions (orange) flow steadily. \"People waiting now\" "
        "peaks at ~1,100 then drains steadily. API Gateway request count peaks at ~11.5K/min -- dominated by status polling."
    )

    # =========================================================================
    pdf.add_page()
    pdf.section_title("6. Numbers: Waiting Room vs. Baseline")

    pdf.sub_title("Comparison Table")
    pdf.add_image_full(IMG(6), "Figure 10: Side-by-side comparison")

    w = [40, 45, 45, 40]
    pdf.table_row(["Metric", "Baseline", "Waiting Room", "Change"], w, bold=True, fill=True)
    pdf.table_row(["Total visitors", "1,520", "1,520", "same"], w)
    pdf.table_row(["Orders accepted", "896", "1,442", "+61%"], w)
    pdf.table_row(["Fans rejected 429", "624 (41%)", "0 (0%)", "eliminated"], w)
    pdf.table_row(["Bots rejected 403", "0", "78", "all blocked"], w)
    pdf.table_row(["Peak orders/sec", "65.0", "19.3", "smoothed"], w)
    pdf.table_row(["Steady rate", "burst", "9.96/sec", "controlled"], w)
    pdf.table_row(["Errors", "0", "0", "same"], w)
    pdf.table_row(["Wait median", "instant", "58.6s", "fairness"], w)
    pdf.table_row(["Wait max", "instant", "124.6s", "everyone served"], w)
    pdf.ln(5)

    pdf.sub_title("Scorecard: Every Rule Passed")
    pdf.add_image_full(IMG(4), "Figure 11: check_run.py -- all 10 rules PASS")

    pdf.sub_title("Stampede Summary: Steady ~10 Orders/Second")
    pdf.add_image_full(IMG(5), "Figure 12: summarize_stampede.py -- steady 9.0-10.5 orders/s")

    pdf.sub_title("Rate Analysis")
    pdf.body_text(
        "Declared rate: 10/sec. Measured: 9.96/sec (100% of configured). Near-perfect accuracy. The time-based "
        "computation max_admitted = elapsed * 10 provides a mathematically smooth admission rate. Each 10-second window "
        "shows 93-105 orders -- tightly clustered around the expected 100.\n\n"
        "The initial burst window (19.3/sec) is higher because early arrivals accumulate eligibility before their first "
        "poll. After ramp-up, the rate settles to steady ~10/sec."
    )

    pdf.sub_title("Wait Time Analysis")
    pdf.body_text(
        "Median: 58.6 seconds | P95: 117.9 seconds | Maximum: 124.6 seconds\n"
        "Polls per visitor: median 11, max 25\n\n"
        "The last fan (position ~1,442) waits about 1,442/10 = 144 seconds from the line opening. Since they join 25 "
        "seconds into the run, their actual wait is about 144-25 = 119 seconds, matching the p95 of 117.9 seconds.\n\n"
        "The maximum wait of 124.6 seconds is well within the 10-minute patience limit. No visitor gave up.\n\n"
        "Total status polls: 16,529 -- the waiting room's own traffic. Every poll is an HTTP request but none touch the backend."
    )

    # =========================================================================
    pdf.add_page()
    pdf.section_title("7. What Limits This Design at 10x Scale")

    pdf.body_text(
        "At 10x scale (15,200 visitors, 1,000 arrivals/sec), the first thing to break is Lambda concurrency."
    )

    pdf.sub_title("Why Lambda Concurrency, Not Redis")
    pdf.body_text(
        "Our stampede generated 16,529 status polls for 1,442 fans. At 10x, that's ~165,000 polls. With a 5-second "
        "poll interval and ~15,000 fans waiting simultaneously, the system would need roughly 3,000 concurrent Lambda "
        "invocations -- far exceeding the account-wide limit of 1,000.\n\n"
        "Redis itself would be fine. Engine CPU peaked at ~6.5% in our run (visible in the custom widget). Even at 10x, "
        "the Redis operations are well within a single micro node's capacity."
    )

    pdf.sub_title("The Fix at 10x")
    pdf.body_text(
        "1. Increase Lambda concurrency quota to 3,000+ (a Support request)\n"
        "2. Increase poll interval from 5 to 15 seconds for visitors far back in line\n"
        "3. Upgrade Redis node to cache.t4g.small or cache.t4g.medium if CPU becomes a concern\n\n"
        "At true Ticketmaster scale (14 million), you'd need a Redis cluster (multiple shards), multi-region deployment, "
        "and the waiting room's own admission layer would need its own rate limiting -- the problem doesn't disappear, "
        "it just moves one layer earlier."
    )

    # =========================================================================
    pdf.section_title("8. One Thing I Would Change")
    pdf.body_text(
        "Add an explicit AdvanceServingCounter Lambda on a 1-second EventBridge schedule instead of time-based computation.\n\n"
        "The time-based approach is elegant and simple, but an explicit counter would allow:\n"
        "1. Pausing admissions during an incident (stop the rule, counter stops)\n"
        "2. Variable-rate admission (faster when healthy, slower when struggling)\n"
        "3. No theoretical clock-skew risk across Lambda instances\n"
        "4. Directly observable admission rate as a CloudWatch metric\n\n"
        "The tradeoff is an extra Lambda, an EventBridge rule, and EventBridge's 1-minute minimum interval creating "
        "chunked admission (600 at a time) rather than smooth. Jittered polling would need to smooth the bursts."
    )

    # =========================================================================
    pdf.add_page()
    pdf.section_title("9. Deployment and Cost")

    pdf.sub_title("Verification Outputs")
    pdf.add_image_full(IMG(7), "Figure 13: verify_kit.py -- PASS, 25 provided files intact")

    w2 = [60, 120]
    pdf.table_row(["Check", "Result"], w2, bold=True, fill=True)
    pdf.table_row(["preflight.py", "PASS (1,000 concurrent executions)"], w2)
    pdf.table_row(["cost_guard.py", "OK ($0.77/day estimated idle cost)"], w2)
    pdf.table_row(["contract_check.py", "PASS (all 9 checks)"], w2)
    pdf.table_row(["check_run.py --configured-rate 10", "PASS (all 10 rules)"], w2)
    pdf.table_row(["verify_kit.py", "PASS (25 provided files intact)"], w2)
    pdf.table_row(["Stack destroyed", "Confirmed (Stack does not exist)"], w2)
    pdf.ln(8)

    pdf.bold_text("Final grade calculation: Execution score x 1.08 (Option C difficulty coefficient).")

    # Save
    pdf.output(OUTPUT)
    print(f"PDF saved to: {OUTPUT}")


if __name__ == "__main__":
    build_pdf()
