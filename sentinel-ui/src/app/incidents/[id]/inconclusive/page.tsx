"use client";

import { useParams } from "next/navigation";
import TopBar from "@/components/TopBar";

export default function InvestigationInconclusive() {
  const params = useParams();
  const id = params?.id as string;

  return (
    <>
      <TopBar
        breadcrumbs={[
          { label: `INC-${id?.slice(0, 4) || "..."}`, href: `/incidents/${id}` },
          { label: "Investigation", active: true },
        ]}
      />
      <main className="flex-1 p-4 overflow-y-auto pb-12 bg-surface">
        <div className="max-w-3xl mx-auto pt-12 text-center">
          <span className="material-symbols-outlined text-[48px] text-outline-variant mb-4">
            search_off
          </span>
          <h1 className="text-xl font-semibold text-on-surface mb-2">
            Investigation Inconclusive
          </h1>
          <p className="text-[13px] text-on-surface-variant max-w-lg mx-auto mb-6">
            The automated investigation could not determine a root cause with
            sufficient confidence. You can provide additional context, adjust the
            investigation scope, or mark this incident for manual review.
          </p>
          <div className="flex gap-3 justify-center">
            <a
              href={`/incidents/${id}`}
              className="px-4 py-2 bg-surface-container border border-outline-variant text-on-surface rounded text-[12px] font-medium hover:bg-surface-container-high transition-colors"
            >
              Back to Incident
            </a>
          </div>
        </div>
      </main>
    </>
  );
}
