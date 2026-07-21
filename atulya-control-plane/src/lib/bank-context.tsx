"use client";

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import { usePathname } from "next/navigation";
import {
  client,
  type MemoryRepoBranchSummary,
  type MemoryRepoStatus,
  type MemoryRepoSummary,
} from "./api";

interface BankContextType {
  currentBank: string | null;
  setCurrentBank: (bank: string | null) => void;
  banks: string[];
  loadBanks: () => Promise<void>;
  currentRepo: MemoryRepoSummary | null;
  repoBranches: MemoryRepoBranchSummary[];
  repoStatus: MemoryRepoStatus | null;
  repoLoading: boolean;
  refreshRepo: () => Promise<void>;
  bankRevision: number;
  bumpBankRevision: () => void;
}

const BankContext = createContext<BankContextType | undefined>(undefined);

export function BankProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [currentBank, setCurrentBank] = useState<string | null>(null);
  const [banks, setBanks] = useState<string[]>([]);
  const [currentRepo, setCurrentRepo] = useState<MemoryRepoSummary | null>(null);
  const [repoBranches, setRepoBranches] = useState<MemoryRepoBranchSummary[]>([]);
  const [repoStatus, setRepoStatus] = useState<MemoryRepoStatus | null>(null);
  const [repoLoading, setRepoLoading] = useState(false);
  const [bankRevision, setBankRevision] = useState(0);
  const repoRequestRef = useRef(0);

  const loadBanks = useCallback(async () => {
    try {
      const response = await client.listBanks();
      // Extract bank_id from each bank object
      const bankIds = response.banks?.map((bank: any) => bank.bank_id) || [];
      setBanks(bankIds);
    } catch (error) {
      console.error("Error loading banks:", error);
    }
  }, []);

  const loadRepoState = useCallback(async (bankId: string | null) => {
    const requestId = repoRequestRef.current + 1;
    repoRequestRef.current = requestId;

    if (!bankId) {
      setCurrentRepo(null);
      setRepoBranches([]);
      setRepoStatus(null);
      setRepoLoading(false);
      return;
    }

    setRepoLoading(true);
    try {
      const repoResponse = await client.getMemoryRepoForBank(bankId);
      if (repoRequestRef.current !== requestId) return;

      const repo = repoResponse.repo;
      setCurrentRepo(repo);

      if (!repo) {
        setRepoBranches([]);
        setRepoStatus(null);
        return;
      }

      const branchesResponse = await client.listMemoryRepoBranchesForBank(bankId);
      if (repoRequestRef.current !== requestId) return;
      setRepoBranches(branchesResponse.branches || []);

      const status = await client.getMemoryRepoStatus(repo.repo_id);
      if (repoRequestRef.current !== requestId) return;
      setRepoStatus(status);
    } catch (error) {
      if (repoRequestRef.current !== requestId) return;
      console.error("Error loading repo state:", error);
      setCurrentRepo(null);
      setRepoBranches([]);
      setRepoStatus(null);
    } finally {
      if (repoRequestRef.current === requestId) {
        setRepoLoading(false);
      }
    }
  }, []);

  const refreshRepo = useCallback(async () => {
    await loadRepoState(currentBank);
  }, [currentBank, loadRepoState]);

  const bumpBankRevision = useCallback(() => {
    setBankRevision((current) => current + 1);
  }, []);

  // Initialize bank from URL on mount
  useEffect(() => {
    const bankMatch = pathname?.match(/^\/banks\/([^/?]+)/);
    if (bankMatch) {
      setCurrentBank(decodeURIComponent(bankMatch[1]));
    }
  }, [pathname]);

  useEffect(() => {
    if (pathname === "/dashboard" || pathname?.startsWith("/banks/")) {
      void loadBanks();
    }
  }, [loadBanks, pathname]);

  useEffect(() => {
    void loadRepoState(currentBank);
  }, [currentBank, loadRepoState]);

  return (
    <BankContext.Provider
      value={{
        currentBank,
        setCurrentBank,
        banks,
        loadBanks,
        currentRepo,
        repoBranches,
        repoStatus,
        repoLoading,
        refreshRepo,
        bankRevision,
        bumpBankRevision,
      }}
    >
      {children}
    </BankContext.Provider>
  );
}

export function useBank() {
  const context = useContext(BankContext);
  if (context === undefined) {
    throw new Error("useBank must be used within a BankProvider");
  }
  return context;
}
