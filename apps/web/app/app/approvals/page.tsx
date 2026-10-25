"use client";

import * as React from "react";

import { ChangeList } from "@/components/app/change-list";
import { PageHeader } from "@/components/app/page-header";
import { Card, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/core";

export default function Approvals() {
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Approval inbox" description="Every proposed change across your sites. Approvals bind to the exact patch version you review — if it changes, it needs approving again." />
      <Tabs defaultValue="pending">
        <TabsList className="mb-4">
          <TabsTrigger value="pending">Needs approval</TabsTrigger>
          <TabsTrigger value="ready">Approved · ready</TabsTrigger>
          <TabsTrigger value="active">In progress</TabsTrigger>
          <TabsTrigger value="problems">Needs attention</TabsTrigger>
          <TabsTrigger value="done">History</TabsTrigger>
        </TabsList>
        {[
          ["pending", "pending_approval", "Inbox zero", "Nothing is waiting for your approval."],
          ["ready", "approved", "Nothing approved and waiting", "Approved changes appear here until executed."],
          ["active", "queued,executing,verifying,awaiting_deploy,rollback_queued", "Nothing running", ""],
          ["problems", "failed,verification_failed,rollback_failed,invalid,blocked", "No problems", "Failed executions and blocked proposals appear here."],
          ["done", "completed,rolled_back,rejected,cancelled,recommendation", "No history yet", ""],
        ].map(([tab, status, title, body]) => (
          <TabsContent key={tab} value={tab}>
            <Card><ChangeList status={status} emptyTitle={title} emptyBody={body} /></Card>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
