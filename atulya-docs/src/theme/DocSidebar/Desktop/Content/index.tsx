import React from 'react';
import Content from '@theme-original/DocSidebar/Desktop/Content';

type Props = React.ComponentProps<typeof Content>;

export default function ContentWrapper(props: Props): React.JSX.Element {
  return <Content {...props} />;
}
