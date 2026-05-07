/**
 *
 * Swizzled DocSidebarItem/Link — adds icon and iconAfter support to sidebar items.
 * Use via customProps.icon / customProps.iconAfter in sidebars.ts.
 * Supports react-icons keys (lu-* / si-*) and image src fallback.
 */
import React from 'react';
import Link from '@theme-original/DocSidebarItem/Link';
import type LinkType from '@theme/DocSidebarItem/Link';
import type {WrapperProps} from '@docusaurus/types';
import type {IconType} from 'react-icons';

import {
  LuBrain, LuRefreshCw, LuSearch, LuMessageSquare, LuLanguages,
  LuZap, LuDatabase, LuGitCompare, LuRocket, LuMemoryStick,
  LuWebhook, LuFileText, LuServer, LuSettings, LuTerminal,
  LuActivity, LuPlug, LuShield, LuPackage, LuBook,
  LuNetwork, LuCode, LuLayers, LuCpu, LuHardDrive,
  LuArrowUpRight, LuBookOpen, LuRss, LuCloud, LuMessageCircle,
  LuChartBar, LuChartColumn, LuStar, LuCircleHelp,
  LuLayoutTemplate, LuFileJson, LuKey, LuUsers,
  LuGlobe, LuBrainCog, LuSparkles, LuBoxes, LuHistory, LuMap,
} from 'react-icons/lu';
import {
  SiGo, SiPython, SiGithub, SiSlack, SiDocker, SiKubernetes,
  SiNodedotjs, SiOpenai, SiAnthropic, SiGooglegemini, SiOllama,
  SiVercel,
} from 'react-icons/si';

const ICON_MAP: Record<string, IconType> = {
  // Lucide
  'lu-brain':           LuBrain,
  'lu-refresh':         LuRefreshCw,
  'lu-search':          LuSearch,
  'lu-message':         LuMessageSquare,
  'lu-languages':       LuLanguages,
  'lu-zap':             LuZap,
  'lu-database':        LuDatabase,
  'lu-compare':         LuGitCompare,
  'lu-rocket':          LuRocket,
  'lu-memory':          LuMemoryStick,
  'lu-webhook':         LuWebhook,
  'lu-file':            LuFileText,
  'lu-file-text':       LuFileText,
  'lu-file-json':       LuFileJson,
  'lu-server':          LuServer,
  'lu-settings':        LuSettings,
  'lu-terminal':        LuTerminal,
  'lu-activity':        LuActivity,
  'lu-plug':            LuPlug,
  'lu-shield':          LuShield,
  'lu-package':         LuPackage,
  'lu-book':            LuBook,
  'lu-book-open':       LuBookOpen,
  'lu-map':             LuMap,
  'lu-network':         LuNetwork,
  'lu-code':            LuCode,
  'lu-layers':          LuLayers,
  'lu-cpu':             LuCpu,
  'lu-hard-drive':      LuHardDrive,
  'lu-arrow-up-right':  LuArrowUpRight,
  'lu-rss':             LuRss,
  'lu-cloud':           LuCloud,
  'lu-message-circle':  LuMessageCircle,
  'lu-chart-bar':       LuChartBar,
  'lu-chart-column':    LuChartColumn,
  'lu-star':            LuStar,
  'lu-circle-help':     LuCircleHelp,
  'lu-layout-template': LuLayoutTemplate,
  'lu-flask':           LuCpu, // no LuFlask in this version — using LuCpu as placeholder
  'lu-key':             LuKey,
  'lu-users':           LuUsers,
  'lu-globe':           LuGlobe,
  'lu-brain-cog':       LuBrainCog,
  'lu-sparkles':        LuSparkles,
  'lu-boxes':           LuBoxes,
  'lu-history':         LuHistory,
  // Simple Icons
  'si-go':              SiGo,
  'si-python':          SiPython,
  'si-github':          SiGithub,
  'si-slack':           SiSlack,
  'si-docker':          SiDocker,
  'si-kubernetes':      SiKubernetes,
  'si-nodedotjs':       SiNodedotjs,
  'si-openai':          SiOpenai,
  'si-anthropic':       SiAnthropic,
  'si-googlegemini':    SiGooglegemini,
  'si-ollama':          SiOllama,
  'si-vercel':          SiVercel,
};

function isImageSource(value: string): boolean {
  return (
    value.startsWith('/') ||
    value.startsWith('./') ||
    value.startsWith('../') ||
    value.startsWith('http://') ||
    value.startsWith('https://') ||
    value.startsWith('data:')
  );
}

type Props = WrapperProps<typeof LinkType>;

export default function LinkWrapper(props: Props): React.JSX.Element {
  const {item} = props;
  const iconKey  = item.customProps?.icon     as string | undefined;
  const iconAfterKey = item.customProps?.iconAfter as string | undefined;

  if (!iconKey && !iconAfterKey) {
    return <Link {...props} />;
  }

  // Resolve icon — react-icon key first, else treat as img src
  const IconComponent = iconKey ? ICON_MAP[iconKey] : undefined;
  const IconAfterComponent = iconAfterKey ? ICON_MAP[iconAfterKey] : undefined;

  const iconNode = iconKey
    ? IconComponent
      ? <IconComponent size={15} style={{flexShrink: 0, opacity: 0.65, marginTop: 1}} />
      : isImageSource(iconKey)
        ? <img src={iconKey} alt="" style={{width: 15, height: 15, flexShrink: 0, objectFit: 'contain'}} />
        : <LuCircleHelp size={15} style={{flexShrink: 0, opacity: 0.35, marginTop: 1}} />
    : null;

  const iconAfterNode = IconAfterComponent
    ? <IconAfterComponent size={12} style={{flexShrink: 0, opacity: 0.4, marginLeft: 'auto'}} />
    : null;

  const modifiedItem = {
    ...item,
    label: (
      <span style={{display: 'flex', alignItems: 'center', gap: 7, width: '100%'}}>
        {iconNode}
        <span style={{flex: 1}}>{item.label}</span>
        {iconAfterNode}
      </span>
    ),
  };

  return <Link {...props} item={modifiedItem} />;
}
