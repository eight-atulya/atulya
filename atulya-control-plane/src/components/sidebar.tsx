"use client";

import { useState } from "react";
import { useBank } from "@/lib/bank-context";
import { useFeatures } from "@/lib/features-context";
import {
  Brain,
  Search,
  Sparkles,
  Database,
  FileText,
  Users,
  ChevronLeft,
  ChevronRight,
  FolderGit2,
  Settings,
  LineChart,
} from "lucide-react";
import { cn } from "@/lib/utils";
import Link from "next/link";

type NavItem =
  | "brain"
  | "recall"
  | "reflect"
  | "data"
  | "documents"
  | "codebases"
  | "entities"
  | "trajectories"
  | "profile";

interface SidebarProps {
  currentTab: NavItem;
  onTabChange: (tab: NavItem) => void;
}

export function Sidebar({ currentTab, onTabChange }: SidebarProps) {
  const { currentBank } = useBank();
  const { features } = useFeatures();
  const [isCollapsed, setIsCollapsed] = useState(true);

  if (!currentBank) {
    return null;
  }

  const navItems = [
    ...(features?.brain_runtime ? [{ id: "brain" as NavItem, label: "Brain", icon: Brain }] : []),
    { id: "data" as NavItem, label: "Memories", icon: Database },
    { id: "recall" as NavItem, label: "Recall", icon: Search },
    { id: "reflect" as NavItem, label: "Reflect", icon: Sparkles },
    { id: "documents" as NavItem, label: "Documents", icon: FileText },
    { id: "codebases" as NavItem, label: "Codebases", icon: FolderGit2 },
    { id: "entities" as NavItem, label: "Entities", icon: Users },
    { id: "trajectories" as NavItem, label: "Trajectories", icon: LineChart },
    { id: "profile" as NavItem, label: "Brain Configuration", icon: Settings },
  ];

  return (
    <aside
      className={cn(
        // h-full + min-h-0: fill the viewport-bound row; nav scrolls independently if needed
        "flex h-full min-h-0 shrink-0 flex-col border-r border-border bg-card transition-all duration-300",
        isCollapsed ? "w-16" : "w-64"
      )}
    >
      <nav className="min-h-0 flex-1 overflow-y-auto p-3 pt-4">
        <ul className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentTab === item.id;
            const href = `/banks/${currentBank}?view=${item.id}`;

            return (
              <li key={item.id}>
                <Link
                  href={href}
                  onClick={(e) => {
                    // For left-click, prevent default and use the callback
                    // This allows the parent to handle navigation without full page reload
                    if (e.button === 0 && !e.ctrlKey && !e.metaKey) {
                      e.preventDefault();
                      onTabChange(item.id);
                    }
                    // Middle-click or Ctrl/Cmd+click will naturally open in new tab
                  }}
                  className={cn(
                    "w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all",
                    isActive
                      ? "bg-primary-gradient text-white shadow-sm"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                    isCollapsed && "justify-center px-0"
                  )}
                  title={isCollapsed ? item.label : undefined}
                >
                  <Icon className="w-5 h-5 flex-shrink-0" />
                  {!isCollapsed && <span>{item.label}</span>}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Pinned footer: stays at bottom of viewport when shell uses fixed height + main scrolls */}
      <div className="shrink-0 border-t border-border p-3">
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className={cn(
            "w-full flex items-center gap-3 px-4 py-2 rounded-lg text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors",
            isCollapsed && "justify-center px-0"
          )}
          title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {isCollapsed ? (
            <ChevronRight className="w-5 h-5" />
          ) : (
            <>
              <ChevronLeft className="w-5 h-5" />
              <span>Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
