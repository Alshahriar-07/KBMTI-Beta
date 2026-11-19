import { Compass } from "lucide-react";
import { Link } from "react-router-dom";

import { EmptyState } from "@/components/ui/EmptyState";

export function NotFoundPage() {
  return (
    <div className="grid h-full place-items-center">
      <EmptyState
        icon={Compass}
        title="Screen not found"
        description="This route is not part of the KBMTI desktop shell."
        action={
          <Link
            to="/"
            className="mt-1 inline-flex h-7 items-center border border-line bg-surface-2 px-2.5 text-[10.5px] font-medium text-ink-muted transition-colors hover:border-line-strong hover:text-ink"
            style={{ borderRadius: 2 }}
          >
            Back to Overview
          </Link>
        }
      />
    </div>
  );
}
