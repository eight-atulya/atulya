import React from 'react';
import Breadcrumbs from '@theme-original/DocBreadcrumbs';
import SkillBanner from '@site/src/components/SkillBanner';

type Props = React.ComponentProps<typeof Breadcrumbs>;

export default function BreadcrumbsWrapper(props: Props): React.JSX.Element {
  return (
    <>
      <Breadcrumbs {...props} />
      <SkillBanner />
    </>
  );
}
