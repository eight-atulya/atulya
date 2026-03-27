import React from 'react';
import Main from '@theme-original/DocPage/Layout/Main';
import {useLocation} from '@docusaurus/router';

type Props = React.ComponentProps<typeof Main>;

export default function MainWrapper(props: Props): React.JSX.Element {
  const location = useLocation();
  const isCookbook = location.pathname.includes('/cookbook');

  return (
    <div style={isCookbook ? {maxWidth: '100%', width: '100%'} : undefined}>
      <Main {...props} />
    </div>
  );
}
