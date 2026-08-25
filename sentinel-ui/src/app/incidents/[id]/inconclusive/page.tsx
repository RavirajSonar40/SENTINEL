import TopBar from "@/components/TopBar";

export default function InvestigationInconclusive() {
  return (
    <>
      <TopBar
        breadcrumbs={[
          { label: "INC-402", href: "/incidents/1" },
          { label: "SEV-1 Critical" },
          { label: "Investigation", active: true },
        ]}
      />
      <main className="flex-1 p-4 overflow-y-auto pb-12 bg-surface">
        <div className="max-w-5xl mx-auto h-full flex flex-col pt-8">
          {/* Abstention Header */}
          <div className="mb-8 border-l-2 border-outline-variant pl-4">
            <h1 className="text-2xl font-semibold text-on-surface mb-2 break-words">
              Analysis Inconclusive
            </h1>
            <p className="text-[14px] text-on-surface-variant max-w-2xl">
              Insufficient Evidence to determine root cause. The automated
              investigation engine requires additional data points to
              confidently synthesize a conclusion for this incident scope.
            </p>
          </div>

          {/* Bento Grid */}
          <div className="grid grid-cols-12 gap-3">
            {/* Missing Evidence Panel */}
            <div className="col-span-12 md:col-span-8 bg-surface-container-low border border-outline-variant p-4 flex flex-col">
              <div className="flex items-center gap-2 mb-4 border-b border-outline-variant pb-2">
                <span className="material-symbols-outlined text-tertiary text-sm">
                  warning
                </span>
                <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface">
                  Missing Telemetry &amp; Context
                </h2>
              </div>
              <div className="flex flex-col gap-1">
                {/* Item 1 */}
                <div className="flex items-start gap-3 p-3 bg-surface border border-outline-variant">
                  <span className="material-symbols-outlined text-outline-variant mt-0.5 text-[16px]">
                    data_alert
                  </span>
                  <div className="flex-grow">
                    <div className="font-mono text-[13px] text-on-surface">
                      Missing logs for auth-api in timeframe T+5
                    </div>
                    <div className="text-[12px] text-on-surface-variant mt-1 break-words">
                      Log aggregation cluster &apos;log-cluster-us-east&apos;
                      reports ingestion delay during incident window.
                    </div>
                  </div>
                </div>
                {/* Item 2 */}
                <div className="flex items-start gap-3 p-3 bg-surface border border-outline-variant">
                  <span className="material-symbols-outlined text-outline-variant mt-0.5 text-[16px]">
                    code_blocks
                  </span>
                  <div className="flex-grow">
                    <div className="font-mono text-[13px] text-on-surface">
                      No recent deployments found in selected repositories
                    </div>
                    <div className="text-[12px] text-on-surface-variant mt-1 break-words">
                      Checked &apos;auth-service&apos; and
                      &apos;user-db&apos;. Last deployment was 72 hours prior
                      to incident start.
                    </div>
                  </div>
                </div>
                {/* Item 3 */}
                <div className="flex items-start gap-3 p-3 bg-surface border border-outline-variant">
                  <span className="material-symbols-outlined text-outline-variant mt-0.5 text-[16px]">
                    network_ping
                  </span>
                  <div className="flex-grow">
                    <div className="font-mono text-[13px] text-on-surface">
                      Network traces truncated
                    </div>
                    <div className="text-[12px] text-on-surface-variant mt-1 break-words">
                      Ingress gateway traces for anomalous IP blocks exceeded
                      sampling limits and were dropped.
                    </div>
                  </div>
                </div>
              </div>
              {/* Actions */}
              <div className="mt-6 pt-4 border-t border-outline-variant flex gap-3">
                <button className="bg-primary/10 border border-primary text-primary hover:bg-primary/20 transition-colors font-mono text-[11px] px-4 py-2 flex items-center gap-2">
                  <span className="material-symbols-outlined text-[16px]">
                    tune
                  </span>
                  Adjust Scope
                </button>
                <button className="bg-transparent border border-outline-variant text-on-surface hover:bg-surface-container-high transition-colors font-mono text-[11px] px-4 py-2 flex items-center gap-2">
                  <span className="material-symbols-outlined text-[16px]">
                    edit_note
                  </span>
                  Provide Manual Context
                </button>
              </div>
            </div>

            {/* Right Side Panels */}
            <div className="col-span-12 md:col-span-4 flex flex-col gap-3">
              {/* Investigation Scope */}
              <div className="bg-surface-container-low border border-outline-variant p-4">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-3 border-b border-outline-variant pb-2">
                  Investigation Scope
                </h3>
                <div className="flex flex-col gap-3 font-mono text-[11px]">
                  <div className="flex justify-between">
                    <span className="text-outline-variant">Timeframe</span>
                    <span className="text-on-surface">T-15m to T+30m</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-outline-variant">Services</span>
                    <span className="text-on-surface text-right break-words">
                      auth-api
                      <br />
                      identity-store
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-outline-variant">
                      Confidence Req
                    </span>
                    <span className="text-on-surface">High (&gt;95%)</span>
                  </div>
                </div>
              </div>

              {/* Sentinel Status */}
              <div className="bg-surface-container-low border border-outline-variant p-4">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-3 border-b border-outline-variant pb-2">
                  Sentinel Status
                </h3>
                <div className="flex items-center gap-2 text-on-surface text-[12px]">
                  <span className="w-2 h-2 rounded-full bg-tertiary" />
                  Engine Idle - Awaiting Input
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}
