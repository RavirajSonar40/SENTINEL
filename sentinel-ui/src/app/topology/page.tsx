"use client";

import React, { useState, useEffect, useMemo } from "react";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { graphApi, GraphNode, GraphEdge, IncidentBlastRadiusReport } from "@/lib/graphApi";

export default function TopologyPage() {
  const { token } = useAuth();
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [nodesByType, setNodesByType] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [activeTab, setActiveTab] = useState<"topology" | "simulator" | "manifest">("topology");

  // Filters
  const [typeFilter, setTypeFilter] = useState<string>("ALL");
  const [tierFilter, setTierFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  // Simulator State
  const [simServiceId, setSimServiceId] = useState<string>("");
  const [simMaxDepth, setSimMaxDepth] = useState<number>(5);
  const [simulating, setSimulating] = useState<boolean>(false);
  const [simReport, setSimReport] = useState<IncidentBlastRadiusReport | null>(null);

  // Manifest Import State
  const [manifestType, setManifestType] = useState<string>("openapi");
  const [manifestRaw, setManifestRaw] = useState<string>("{\n  \"paths\": {\n    \"/api/v1/checkout\": {\n      \"post\": {\"summary\": \"Process Checkout\"}\n    }\n  }\n}");
  const [importing, setImporting] = useState<boolean>(false);
  const [importStatus, setImportStatus] = useState<string | null>(null);

  const fetchTopology = async () => {
    try {
      setLoading(true);
      const res = await graphApi.getTopology({
        node_type: typeFilter !== "ALL" ? typeFilter : undefined,
        tier: tierFilter !== "ALL" ? tierFilter : undefined,
        include_stale: true,
      }, token || undefined);
      setNodes(res.nodes);
      setEdges(res.edges);
      setNodesByType(res.nodes_by_type || {});
    } catch (err) {
      console.error("Failed to load topology:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTopology();
  }, [typeFilter, tierFilter, token]);

  const handleSyncCatalog = async () => {
    try {
      setSyncing(true);
      await graphApi.syncCatalog(token || undefined);
      await fetchTopology();
    } catch (err) {
      console.error("Sync error:", err);
    } finally {
      setSyncing(false);
    }
  };

  const handleRunSimulation = async () => {
    if (!simServiceId) return;
    try {
      setSimulating(true);
      const res = await graphApi.simulateBlastRadius({
        service_id: simServiceId,
        max_depth: simMaxDepth,
      }, token || undefined);
      setSimReport(res);
    } catch (err) {
      console.error("Simulation error:", err);
    } finally {
      setSimulating(false);
    }
  };

  const handleImportManifest = async () => {
    try {
      setImporting(true);
      setImportStatus(null);
      const parsed = JSON.parse(manifestRaw);
      const res = await graphApi.importManifest({
        manifest_type: manifestType,
        content: parsed,
      }, token || undefined);
      setImportStatus(`Success! Created ${res.nodes_created || 0} nodes and ${res.edges_created || 0} edges.`);
      await fetchTopology();
    } catch (err: any) {
      setImportStatus(`Import failed: ${err.message}`);
    } finally {
      setImporting(false);
    }
  };

  const servicesList = useMemo(() => {
    return nodes.filter((n) => n.node_type === "SERVICE" && n.entity_id);
  }, [nodes]);

  const filteredNodes = useMemo(() => {
    return nodes.filter((n) => {
      if (searchQuery && !n.name.toLowerCase().includes(searchQuery.toLowerCase()) && !n.identifier.toLowerCase().includes(searchQuery.toLowerCase())) {
        return false;
      }
      return true;
    });
  }, [nodes, searchQuery]);

  const nodeEdges = useMemo(() => {
    if (!selectedNode) return { out: [], in: [] };
    const outEdges = edges.filter((e) => e.source_node_id === selectedNode.id);
    const inEdges = edges.filter((e) => e.target_node_id === selectedNode.id);
    return { out: outEdges, in: inEdges };
  }, [selectedNode, edges]);

  return (
    <>
      <TopBar
        title="System Service Graph"
        subtitle="Multi-entity topology, live OpenTelemetry trace discovery, and multi-hop customer impact analysis."
        actions={
          <div className="flex items-center gap-2 mr-4">
            <button
              onClick={handleSyncCatalog}
              disabled={syncing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-surface-container-high hover:bg-surface-container-highest text-[11px] font-semibold uppercase tracking-wider border border-outline-variant transition-colors disabled:opacity-50"
            >
              <span className={`material-symbols-outlined text-[14px] ${syncing ? "animate-spin" : ""}`}>
                sync
              </span>
              {syncing ? "Syncing..." : "Sync Catalog"}
            </button>
            <button
              onClick={() => setActiveTab("simulator")}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-primary text-on-primary text-[11px] font-semibold uppercase tracking-wider hover:bg-primary/90 transition-colors shadow-sm"
            >
              <span className="material-symbols-outlined text-[14px]">radar</span>
              Simulate Blast Radius
            </button>
          </div>
        }
      />

      <main className="flex-1 p-6 overflow-x-auto pb-10 space-y-6">

        {/* Metrics Row */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant">
            <div className="text-xs font-medium text-on-surface-variant uppercase">Total Nodes</div>
            <div className="text-2xl font-bold mt-1 text-primary">{nodes.length}</div>
          </div>
          <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant">
            <div className="text-xs font-medium text-on-surface-variant uppercase">Total Edges</div>
            <div className="text-2xl font-bold mt-1 text-on-surface">{edges.length}</div>
          </div>
          <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant">
            <div className="text-xs font-medium text-on-surface-variant uppercase">Services</div>
            <div className="text-2xl font-bold mt-1 text-emerald-400">{nodesByType["SERVICE"] || 0}</div>
          </div>
          <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant">
            <div className="text-xs font-medium text-on-surface-variant uppercase">Databases & Cache</div>
            <div className="text-2xl font-bold mt-1 text-amber-400">{nodesByType["DATABASE"] || 0}</div>
          </div>
          <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant">
            <div className="text-xs font-medium text-on-surface-variant uppercase">Queues & Brokers</div>
            <div className="text-2xl font-bold mt-1 text-purple-400">{nodesByType["QUEUE"] || 0}</div>
          </div>
          <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant">
            <div className="text-xs font-medium text-on-surface-variant uppercase">Repositories</div>
            <div className="text-2xl font-bold mt-1 text-sky-400">{nodesByType["REPOSITORY"] || 0}</div>
          </div>
        </div>

        {/* Tabs Bar */}
        <div className="flex border-b border-outline-variant gap-6">
          <button
            onClick={() => setActiveTab("topology")}
            className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
              activeTab === "topology"
                ? "border-primary text-primary"
                : "border-transparent text-on-surface-variant hover:text-on-surface"
            }`}
          >
            <span className="material-symbols-outlined text-[18px]">hub</span>
            Topology Explorer
          </button>
          <button
            onClick={() => setActiveTab("simulator")}
            className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
              activeTab === "simulator"
                ? "border-primary text-primary"
                : "border-transparent text-on-surface-variant hover:text-on-surface"
            }`}
          >
            <span className="material-symbols-outlined text-[18px]">radar</span>
            Blast Radius Simulator
          </button>
          <button
            onClick={() => setActiveTab("manifest")}
            className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
              activeTab === "manifest"
                ? "border-primary text-primary"
                : "border-transparent text-on-surface-variant hover:text-on-surface"
            }`}
          >
            <span className="material-symbols-outlined text-[18px]">file_upload</span>
            Manifest Importer
          </button>
        </div>

        {/* TAB 1: TOPOLOGY EXPLORER */}
        {activeTab === "topology" && (
          <div className="space-y-4">
            {/* Filter Bar */}
            <div className="flex flex-wrap items-center gap-3 bg-surface-container-low p-3.5 rounded-xl border border-outline-variant">
              <div className="relative flex-1 min-w-[200px]">
                <span className="material-symbols-outlined absolute left-3 top-2.5 text-on-surface-variant text-[18px]">
                  search
                </span>
                <input
                  type="text"
                  placeholder="Search entities by name or identifier..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-9 pr-4 py-1.5 bg-surface-container-lowest border border-outline-variant rounded-lg text-sm focus:outline-none focus:border-primary"
                />
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs text-on-surface-variant font-medium">Type:</span>
                <select
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value)}
                  className="bg-surface-container-lowest border border-outline-variant rounded-lg px-3 py-1.5 text-xs font-medium focus:outline-none focus:border-primary"
                >
                  <option value="ALL">All Types</option>
                  <option value="SERVICE">Services</option>
                  <option value="REPOSITORY">Repositories</option>
                  <option value="DATABASE">Databases</option>
                  <option value="QUEUE">Queues</option>
                  <option value="ENDPOINT">Endpoints</option>
                  <option value="ENVIRONMENT">Environments</option>
                  <option value="TEAM">Teams</option>
                </select>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs text-on-surface-variant font-medium">Tier:</span>
                <select
                  value={tierFilter}
                  onChange={(e) => setTierFilter(e.target.value)}
                  className="bg-surface-container-lowest border border-outline-variant rounded-lg px-3 py-1.5 text-xs font-medium focus:outline-none focus:border-primary"
                >
                  <option value="ALL">All Tiers</option>
                  <option value="critical">Critical</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </div>
            </div>

            {/* Grid & Inspector */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Nodes List */}
              <div className="lg:col-span-2 space-y-3">
                {loading ? (
                  <div className="p-12 text-center text-on-surface-variant">
                    <span className="material-symbols-outlined animate-spin text-[32px] mb-2">progress_activity</span>
                    <p className="text-sm">Loading system topology graph...</p>
                  </div>
                ) : filteredNodes.length === 0 ? (
                  <div className="p-12 text-center bg-surface-container-low rounded-xl border border-outline-variant text-on-surface-variant">
                    <span className="material-symbols-outlined text-[36px] mb-2 text-on-surface-variant/40">account_tree</span>
                    <p className="text-sm font-medium">No topology nodes found.</p>
                    <p className="text-xs text-on-surface-variant/70 mt-1">
                      Click &quot;Sync from Catalog&quot; to populate graph nodes from registered services.
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-[700px] overflow-y-auto pr-1">
                    {filteredNodes.map((n) => {
                      const isSelected = selectedNode?.id === n.id;
                      const outCount = edges.filter((e) => e.source_node_id === n.id).length;
                      const inCount = edges.filter((e) => e.target_node_id === n.id).length;

                      return (
                        <div
                          key={n.id}
                          onClick={() => setSelectedNode(n)}
                          className={`p-4 rounded-xl border cursor-pointer transition-all ${
                            isSelected
                              ? "bg-surface-container-high border-primary shadow-md ring-1 ring-primary/40"
                              : "bg-surface-container-low border-outline-variant hover:border-outline hover:bg-surface-container"
                          }`}
                        >
                          <div className="flex items-start justify-between">
                            <div className="flex items-center gap-2">
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-surface-container-highest text-on-surface-variant">
                                {n.node_type}
                              </span>
                              {n.tier && (
                                <span
                                  className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                                    n.tier === "critical"
                                      ? "bg-rose-500/20 text-rose-400 border border-rose-500/30"
                                      : n.tier === "high"
                                      ? "bg-amber-500/20 text-amber-400"
                                      : "bg-surface-container-highest text-on-surface-variant"
                                  }`}
                                >
                                  {n.tier}
                                </span>
                              )}
                            </div>
                            <span className="text-[11px] text-on-surface-variant/70 font-mono">
                              {outCount} out / {inCount} in
                            </span>
                          </div>

                          <div className="font-semibold text-sm mt-2 text-on-surface truncate">{n.name}</div>
                          <div className="text-xs text-on-surface-variant font-mono truncate mt-0.5">{n.identifier}</div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Edge & Details Inspector */}
              <div className="bg-surface-container-low rounded-xl border border-outline-variant p-5 flex flex-col h-full max-h-[700px] overflow-y-auto">
                <h3 className="font-semibold text-sm border-b border-outline-variant pb-3 flex items-center gap-2">
                  <span className="material-symbols-outlined text-[18px] text-primary">manage_search</span>
                  Entity Inspector
                </h3>

                {selectedNode ? (
                  <div className="mt-4 space-y-4 text-xs">
                    <div>
                      <div className="text-on-surface-variant font-medium">Name</div>
                      <div className="text-sm font-bold text-on-surface mt-0.5">{selectedNode.name}</div>
                    </div>

                    <div>
                      <div className="text-on-surface-variant font-medium">Identifier</div>
                      <div className="font-mono text-on-surface-variant bg-surface-container-lowest p-2 rounded border border-outline-variant mt-0.5 break-all">
                        {selectedNode.identifier}
                      </div>
                    </div>

                    {/* Outgoing Edges */}
                    <div>
                      <div className="text-on-surface-variant font-semibold uppercase tracking-wider text-[11px] mb-2">
                        Outgoing Call / Dependency Edges ({nodeEdges.out.length})
                      </div>
                      {nodeEdges.out.length === 0 ? (
                        <div className="text-on-surface-variant/60 italic">No outgoing edges.</div>
                      ) : (
                        <div className="space-y-2">
                          {nodeEdges.out.map((e) => {
                            const tgt = nodes.find((n) => n.id === e.target_node_id);
                            return (
                              <div key={e.id} className="p-2.5 rounded bg-surface-container-lowest border border-outline-variant">
                                <div className="flex items-center justify-between font-semibold">
                                  <span className="text-primary">{e.edge_type}</span>
                                  <span className={`px-1.5 py-0.2 rounded text-[10px] ${e.criticality === "hard" ? "bg-rose-500/20 text-rose-300" : "bg-amber-500/20 text-amber-300"}`}>
                                    {e.criticality.toUpperCase()}
                                  </span>
                                </div>
                                <div className="text-on-surface font-medium mt-1 truncate">
                                  &rarr; {tgt?.name || e.target_node_id}
                                </div>
                                <div className="text-[10px] text-on-surface-variant mt-1 flex items-center justify-between">
                                  <span>Confidence: {(e.confidence * 100).toFixed(0)}%</span>
                                  <span className="italic">{e.source}</span>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>

                    {/* Incoming Callers */}
                    <div>
                      <div className="text-on-surface-variant font-semibold uppercase tracking-wider text-[11px] mb-2">
                        Incoming Callers ({nodeEdges.in.length})
                      </div>
                      {nodeEdges.in.length === 0 ? (
                        <div className="text-on-surface-variant/60 italic">No incoming caller edges.</div>
                      ) : (
                        <div className="space-y-2">
                          {nodeEdges.in.map((e) => {
                            const src = nodes.find((n) => n.id === e.source_node_id);
                            return (
                              <div key={e.id} className="p-2.5 rounded bg-surface-container-lowest border border-outline-variant">
                                <div className="flex items-center justify-between font-semibold">
                                  <span className="text-emerald-400">&larr; {e.edge_type}</span>
                                  <span className={`px-1.5 py-0.2 rounded text-[10px] ${e.criticality === "hard" ? "bg-rose-500/20 text-rose-300" : "bg-amber-500/20 text-amber-300"}`}>
                                    {e.criticality.toUpperCase()}
                                  </span>
                                </div>
                                <div className="text-on-surface font-medium mt-1 truncate">
                                  {src?.name || e.source_node_id}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>

                    {selectedNode.node_type === "SERVICE" && (
                      <button
                        onClick={() => {
                          setSimServiceId(selectedNode.entity_id || selectedNode.id);
                          setActiveTab("simulator");
                        }}
                        className="w-full mt-2 py-2 rounded-lg bg-primary/20 hover:bg-primary/30 text-primary font-medium text-xs border border-primary/30 transition-colors"
                      >
                        Simulate Blast Radius for {selectedNode.name} &rarr;
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="flex-1 flex flex-col items-center justify-center text-center p-8 text-on-surface-variant">
                    <span className="material-symbols-outlined text-[36px] text-on-surface-variant/30 mb-2">touch_app</span>
                    <p className="text-xs">Select any topology node on the left to inspect outgoing edges, incoming callers, and confidence metadata.</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: BLAST RADIUS SIMULATOR */}
        {activeTab === "simulator" && (
          <div className="space-y-6">
            {/* Simulation Controls */}
            <div className="bg-surface-container-low p-5 rounded-xl border border-outline-variant space-y-4">
              <h3 className="font-semibold text-sm flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-[20px]">radar</span>
                Multi-Hop Blast Radius Simulator
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="text-xs font-medium text-on-surface-variant">Target Root Service</label>
                  <select
                    value={simServiceId}
                    onChange={(e) => setSimServiceId(e.target.value)}
                    className="w-full mt-1 bg-surface-container-lowest border border-outline-variant rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-primary"
                  >
                    <option value="">-- Select a service to simulate --</option>
                    {servicesList.map((s) => (
                      <option key={s.id} value={s.entity_id || s.id}>
                        {s.name} ({s.tier || "tier-2"})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="text-xs font-medium text-on-surface-variant">Max Downstream Traversal Depth</label>
                  <input
                    type="number"
                    min={1}
                    max={15}
                    value={simMaxDepth}
                    onChange={(e) => setSimMaxDepth(parseInt(e.target.value) || 5)}
                    className="w-full mt-1 bg-surface-container-lowest border border-outline-variant rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-primary"
                  />
                </div>

                <div className="flex items-end">
                  <button
                    onClick={handleRunSimulation}
                    disabled={!simServiceId || simulating}
                    className="w-full py-2.5 px-4 rounded-lg bg-primary hover:bg-primary/90 text-on-primary font-medium text-sm transition-colors shadow-sm disabled:opacity-50 flex items-center justify-center gap-2"
                  >
                    <span className={`material-symbols-outlined text-[18px] ${simulating ? "animate-spin" : ""}`}>
                      {simulating ? "progress_activity" : "bolt"}
                    </span>
                    {simulating ? "Analyzing Graph..." : "Execute Simulation"}
                  </button>
                </div>
              </div>
            </div>

            {/* Simulation Results */}
            {simReport && (
              <div className="space-y-6">
                {/* Customer Impact Summary Banner */}
                <div className="bg-gradient-to-r from-rose-950/40 via-surface-container-low to-surface-container-low p-6 rounded-2xl border border-rose-500/30">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="px-2.5 py-0.5 rounded-full text-xs font-bold uppercase bg-rose-500/20 text-rose-300 border border-rose-500/40">
                          {simReport.customer_impact.traffic_impact_mode.toUpperCase()} IMPACT
                        </span>
                        <span className="text-xs text-on-surface-variant">
                          Confidence: <strong className="text-on-surface">{simReport.customer_impact.traffic_confidence.toUpperCase()}</strong>
                        </span>
                      </div>
                      <h2 className="text-xl font-bold mt-2">
                        Estimated Customer Impact: {simReport.customer_impact.traffic_percent || 0}% Traffic Degradation
                      </h2>
                      <p className="text-xs text-on-surface-variant mt-1 max-w-3xl">
                        {simReport.customer_impact.calculation_basis}
                      </p>
                    </div>

                    <div className="flex items-center gap-4 bg-surface-container-lowest/80 px-5 py-3 rounded-xl border border-outline-variant">
                      <div className="text-center">
                        <div className="text-xs text-on-surface-variant">Traffic At Risk</div>
                        <div className="text-2xl font-black text-rose-400 mt-0.5">
                          {simReport.customer_impact.traffic_percent || 0}%
                        </div>
                      </div>
                      <div className="h-8 w-px bg-outline-variant" />
                      <div className="text-center">
                        <div className="text-xs text-on-surface-variant">Users Affected</div>
                        <div className="text-2xl font-black text-amber-400 mt-0.5">
                          {simReport.customer_impact.user_percent || 0}%
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Downstream & Upstream Breakdown */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {/* Downstream Affected Callers */}
                  <div className="bg-surface-container-low p-5 rounded-xl border border-outline-variant space-y-3">
                    <h3 className="font-semibold text-sm flex items-center justify-between">
                      <span className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-rose-400 text-[18px]">call_received</span>
                        Downstream Affected Callers ({simReport.indirect_services.length})
                      </span>
                      <span className="text-xs text-on-surface-variant">Ordered by graph distance</span>
                    </h3>

                    {simReport.indirect_services.length === 0 ? (
                      <div className="text-xs text-on-surface-variant/70 italic p-4 text-center">
                        No downstream callers affected.
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {simReport.indirect_services.map((svc, idx) => (
                          <div
                            key={idx}
                            className="p-3 bg-surface-container-lowest rounded-lg border border-outline-variant flex items-center justify-between"
                          >
                            <div>
                              <div className="flex items-center gap-2 font-semibold text-sm">
                                <span>{svc.name}</span>
                                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${svc.impact_type === "observed" ? "bg-rose-500/20 text-rose-300" : "bg-sky-500/20 text-sky-300"}`}>
                                  {svc.impact_type.toUpperCase()}
                                </span>
                                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${svc.impact_level === "outage" ? "bg-rose-500/20 text-rose-400" : "bg-amber-500/20 text-amber-400"}`}>
                                  {svc.impact_level.toUpperCase()}
                                </span>
                              </div>
                              <div className="text-xs text-on-surface-variant mt-1">
                                Distance: {svc.distance} &bull; Path: {svc.path.join(" \u2192 ")}
                              </div>
                            </div>
                            <span className={`px-2 py-1 rounded text-xs font-mono font-bold ${svc.criticality === "hard" ? "text-rose-400" : "text-amber-400"}`}>
                              {svc.criticality.toUpperCase()}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Multi-Repository Categorization */}
                  <div className="bg-surface-container-low p-5 rounded-xl border border-outline-variant space-y-3">
                    <h3 className="font-semibold text-sm flex items-center gap-2">
                      <span className="material-symbols-outlined text-primary text-[18px]">folder_copy</span>
                      Multi-Repository Action Scopes ({simReport.affected_repositories.length})
                    </h3>

                    <div className="space-y-2">
                      {simReport.affected_repositories.map((repo, idx) => (
                        <div
                          key={idx}
                          className="p-3 bg-surface-container-lowest rounded-lg border border-outline-variant flex items-center justify-between"
                        >
                          <div>
                            <div className="font-semibold text-sm">{repo.name}</div>
                            <div className="text-xs text-on-surface-variant mt-0.5">Role: {repo.role}</div>
                          </div>

                          <div>
                            {repo.remediation_target ? (
                              <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                                Remediation Target
                              </span>
                            ) : (
                              <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-surface-container-highest text-on-surface-variant border border-outline-variant">
                                Evidence Only
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* TAB 3: MANIFEST IMPORTER */}
        {activeTab === "manifest" && (
          <div className="bg-surface-container-low p-6 rounded-xl border border-outline-variant space-y-4 max-w-3xl">
            <h3 className="font-semibold text-base flex items-center gap-2">
              <span className="material-symbols-outlined text-primary text-[20px]">upload_file</span>
              OpenAPI / Kubernetes Spec Importer
            </h3>
            <p className="text-xs text-on-surface-variant">
              Paste OpenAPI 3.0 path specs or Kubernetes manifest YAML/JSON to discover HTTP endpoints and link them to services.
            </p>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-on-surface-variant">Manifest Type</label>
                <select
                  value={manifestType}
                  onChange={(e) => setManifestType(e.target.value)}
                  className="w-full mt-1 bg-surface-container-lowest border border-outline-variant rounded-lg px-3 py-2 text-sm"
                >
                  <option value="openapi">OpenAPI 3.0 Spec (JSON)</option>
                  <option value="k8s">Kubernetes Workloads</option>
                  <option value="docker_compose">Docker Compose Spec</option>
                </select>
              </div>

              <div>
                <label className="text-xs font-medium text-on-surface-variant">Manifest Content (JSON)</label>
                <textarea
                  rows={8}
                  value={manifestRaw}
                  onChange={(e) => setManifestRaw(e.target.value)}
                  className="w-full mt-1 font-mono text-xs bg-surface-container-lowest border border-outline-variant rounded-lg p-3 focus:outline-none focus:border-primary"
                />
              </div>

              {importStatus && (
                <div className={`p-3 rounded-lg text-xs font-medium ${importStatus.includes("Success") ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30" : "bg-rose-500/10 text-rose-400 border border-rose-500/30"}`}>
                  {importStatus}
                </div>
              )}

              <button
                onClick={handleImportManifest}
                disabled={importing}
                className="py-2.5 px-5 rounded-lg bg-primary hover:bg-primary/90 text-on-primary text-sm font-medium transition-colors disabled:opacity-50"
              >
                {importing ? "Importing..." : "Parse and Import to Graph"}
              </button>
            </div>
          </div>
        )}
      </main>
    </>
  );
}
