import type { ReactNode } from "react";

export function Icon({
  name,
}: {
  name: "activity" | "venue" | "time" | "bill" | "profile" | "menu" | "admin";
}) {
  const paths: Record<string, ReactNode> = {
    activity: (
      <>
        <rect x="4" y="5" width="16" height="16" rx="3" />
        <path d="M8 3v4m8-4v4M4 11h16m-11 5 2 2 4-4" />
      </>
    ),
    venue: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="1" />
        <path d="M12 5v14M6 5v14m12-14v14M3 12h18" />
      </>
    ),
    time: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    bill: (
      <>
        <path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3Z" />
        <path d="M9 8h6m-6 4h6" />
      </>
    ),
    profile: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21v-2a8 8 0 0 1 16 0v2" />
      </>
    ),
    admin: (
      <>
        <path d="m12 3 8 3v6c0 5-8 9-8 9S4 17 4 12V6l8-3Z" />
        <path d="m8 12 3 3 5-6" />
      </>
    ),
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  };
  return (
    <svg
      className="nav-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
export function ShuttleMark() {
  return (
    <svg className="shuttle-mark" viewBox="0 0 40 40" aria-hidden="true">
      <rect width="40" height="40" rx="12" fill="currentColor" />
      <g
        transform="rotate(30 20 20)"
        fill="none"
        stroke="white"
        strokeWidth="1.7"
        strokeLinejoin="round"
      >
        <path d="m10 10 5 17h10l5-17-5-3H15Z" />
        <path d="m15 7 3 20m7-20-3 20M10 10h20M15 27a5 5 0 0 0 10 0" />
      </g>
    </svg>
  );
}
export function CourtIllustration({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`court-illustration ${className}`}
      viewBox="0 0 420 260"
      fill="none"
      aria-hidden="true"
    >
      <g transform="translate(38 44) rotate(-12 160 88)">
        <rect x="-14" y="-14" width="348" height="204" rx="12" fill="#487BE9" />
        <rect
          width="320"
          height="176"
          rx="1"
          fill="#2D64DD"
          stroke="#E0EAFF"
          strokeWidth="2"
        />
        <path
          d="M0 18h320M0 158h320M24 0v176M296 0v176M115 0v176M205 0v176M0 88h115m90 0h115"
          stroke="#DCE7FF"
          strokeWidth="1.6"
        />
        <path d="M160-14v204" stroke="white" strokeWidth="2.5" />
        <circle cx="94" cy="119" r="12" fill="#C9EADF" />
        <circle cx="248" cy="48" r="12" fill="#F3D47A" />
        <path
          d="M107 108q73-94 126-57"
          stroke="white"
          strokeDasharray="4 6"
          strokeWidth="1.6"
        />
        <path d="m216 46 17 5-11 13" stroke="white" strokeWidth="1.6" />
      </g>
    </svg>
  );
}
