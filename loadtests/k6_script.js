/**
 * k6 load test — ramp-up to MAX_VUS concurrent users
 *
 * Environment variables:
 *   BASE_URL        — target application URL
 *   MAX_VUS         — peak virtual users (default: 100)
 *   SUMMARY_PATH    — file path to write JSON summary (optional)
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const MAX_VUS = parseInt(__ENV.MAX_VUS || "100", 10);
const SUMMARY_PATH = __ENV.SUMMARY_PATH || "";

const errorRate = new Rate("errors");

export const options = {
  stages: [
    { duration: "20s", target: Math.min(MAX_VUS, 10) },   // warm-up
    { duration: "40s", target: MAX_VUS },                   // ramp to peak
    { duration: "30s", target: MAX_VUS },                   // hold at peak
    { duration: "10s", target: 0 },                         // ramp down
  ],
  thresholds: {
    http_req_duration: ["p(95)<2000"],
    http_req_failed: ["rate<0.05"],
    errors: ["rate<0.05"],
  },
};

export default function () {
  const params = {
    headers: { "Content-Type": "application/json" },
    timeout: "10s",
  };

  // Health check
  const healthRes = http.get(`${BASE_URL}/health`, params);
  const healthOk = check(healthRes, {
    "health status 200": (r) => r.status === 200,
  });
  errorRate.add(!healthOk);

  // Root page
  const rootRes = http.get(`${BASE_URL}/`, params);
  const rootOk = check(rootRes, {
    "root status 200": (r) => r.status === 200 || r.status === 404,
  });
  errorRate.add(!rootOk);

  sleep(1);
}

export function handleSummary(data) {
  const summary = JSON.stringify(
    {
      metrics: {
        http_req_duration: data.metrics.http_req_duration
          ? data.metrics.http_req_duration.values
          : {},
        http_req_failed: data.metrics.http_req_failed
          ? data.metrics.http_req_failed.values
          : {},
        http_reqs: data.metrics.http_reqs
          ? data.metrics.http_reqs.values
          : {},
        errors: data.metrics.errors
          ? data.metrics.errors.values
          : {},
      },
    },
    null,
    2
  );

  const output = { stdout: summary + "\n" };

  // Also write to file if SUMMARY_PATH is set
  if (SUMMARY_PATH) {
    output[SUMMARY_PATH] = summary;
  }

  return output;
}
