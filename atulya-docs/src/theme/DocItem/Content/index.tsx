import React from 'react';
import DocItemContent from '@theme-original/DocItem/Content';

type Props = React.ComponentProps<typeof DocItemContent>;

export default function DocItemContentWrapper(props: Props): React.JSX.Element {
  return <DocItemContent {...props} />;
}
