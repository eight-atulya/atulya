import React from 'react';
import Sidebar from '@theme-original/DocPage/Layout/Sidebar';
import {useLocation} from '@docusaurus/router';
import SkillBanner from '@site/src/components/SkillBanner';

type Props = React.ComponentProps<typeof Sidebar>;

export default function SidebarWrapper(props: Props): React.JSX.Element | null {
  const location = useLocation();
  const isCookbook = location.pathname.includes('/cookbook');

  // Don't render sidebar for cookbook pages
  if (isCookbook) {
    return null;
  }

  return (
    <>
      <SkillBanner />
      <Sidebar {...props} />
    </>
  );
}
