"use client";

import Image from "next/image";

const partnerLogoSrc = process.env.NEXT_PUBLIC_ATULYA_CP_BRAND_LOGO_SRC?.trim();
const partnerExtendedLogoSrc = process.env.NEXT_PUBLIC_ATULYA_CP_BRAND_LOGO_EXTENDED_SRC?.trim();
const partnerLogoAlt = process.env.NEXT_PUBLIC_ATULYA_CP_BRAND_LOGO_ALT?.trim() || "Partner brand";
const partnerLogoVariant =
  process.env.NEXT_PUBLIC_ATULYA_CP_BRAND_LOGO_VARIANT?.trim().toLowerCase() === "extended"
    ? "extended"
    : "compact";

function resolvePartnerLogo() {
  if (partnerLogoVariant === "extended" && partnerExtendedLogoSrc) {
    return { src: partnerExtendedLogoSrc, variant: "extended" as const };
  }
  if (partnerLogoSrc) return { src: partnerLogoSrc, variant: "compact" as const };
  return null;
}

export function HeaderBrandLockup() {
  const partnerLogo = resolvePartnerLogo();

  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <Image
        src="/logo.png"
        alt="Atulya"
        width={34}
        height={34}
        className="h-[34px] w-auto shrink-0"
        unoptimized
      />
      {partnerLogo ? (
        <>
          <span className="h-6 w-px shrink-0 bg-border" aria-hidden="true" />
          <span
            className="inline-flex h-8 max-w-[9rem] shrink-0 items-center rounded-md border border-border/70 bg-background/45 px-2 py-1"
            title={`${partnerLogoAlt} branding`}
          >
            <img
              src={partnerLogo.src}
              alt={partnerLogoAlt}
              className={
                partnerLogo.variant === "extended"
                  ? "h-5 max-w-[7.5rem] object-contain"
                  : "h-5 max-w-10 object-contain"
              }
            />
          </span>
        </>
      ) : null}
    </span>
  );
}
