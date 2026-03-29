"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

interface CopyButtonProps {
  text: string;
  label?: string;
  copiedLabel?: string;
  toastLabel?: string;
  className?: string;
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  size?: "default" | "sm" | "lg" | "icon";
  iconOnly?: boolean;
}

export function CopyButton({
  text,
  label = "Copy",
  copiedLabel = "Copied",
  toastLabel = "Copied to clipboard",
  className,
  variant = "outline",
  size = "sm",
  iconOnly = false,
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast.success(toastLabel);
      window.setTimeout(() => setCopied(false), 1500);
    } catch (error) {
      console.error("Failed to copy text:", error);
      toast.error("Failed to copy");
    }
  };

  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      className={className}
      onClick={handleCopy}
      title={copied ? copiedLabel : label}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {!iconOnly && <span>{copied ? copiedLabel : label}</span>}
    </Button>
  );
}
