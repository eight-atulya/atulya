/**
 *
 * SupportedGrids — pre-built IconGrid instances for Atulya's supported
 * clients, integrations, and LLM providers.
 *
 * Usage in MDX:
 *   import {ClientsGrid, LLMProvidersGrid, IntegrationsGrid} from '@site/src/components/SupportedGrids';
 *   <ClientsGrid />
 */
import React from 'react';
import type {IconType} from 'react-icons';
import {IconGrid} from './IconGrid';
import {
  SiPython, SiGo, SiOpenai, SiAnthropic, SiGooglegemini, SiOllama, SiVercel,
} from 'react-icons/si';
import {
  LuTerminal, LuZap, LuBrainCog, LuSparkles, LuGlobe, LuCloud, LuLayers, LuPlug,
} from 'react-icons/lu';

const OpenAICompatibleIcon: IconType = ({size = 26, ...props}) => (
  <span style={{position: 'relative', display: 'inline-flex'}}>
    <SiOpenai size={size} {...props} />
    <span style={{
      position: 'absolute', bottom: -3, right: -6,
      fontSize: Math.round((size as number) * 0.48), fontWeight: 900, lineHeight: 1,
      color: 'currentColor',
    }}>+</span>
  </span>
);

export function ClientsGrid(): React.JSX.Element {
  return (
    <IconGrid items={[
      {label: 'Python',     icon: SiPython,   href: '/sdks/python'},
      {label: 'TypeScript', imgSrc: '/img/icons/typescript.png', href: '/sdks/nodejs'},
      {label: 'Go',         icon: SiGo,       href: '/sdks/go'},
      {label: 'CLI',        icon: LuTerminal, href: '/sdks/cli'},
      {label: 'HTTP',       icon: LuGlobe,    href: '/developer/api/quickstart'},
    ]} />
  );
}

export function IntegrationsGrid(): React.JSX.Element {
  return (
    <IconGrid items={[
      {label: 'MCP Server',  imgSrc: '/img/icons/mcp.png',      href: '/sdks/integrations/local-mcp'},
      {label: 'LiteLLM',     imgSrc: '/img/icons/litellm.png',  href: '/sdks/integrations/litellm'},
      {label: 'OpenClaw',    imgSrc: '/img/icons/openclaw.png', href: '/sdks/integrations/openclaw'},
      {label: 'Vercel AI',   icon: SiVercel,                    href: '/sdks/integrations/ai-sdk'},
      {label: 'Skills',      imgSrc: '/img/icons/skills.png',   href: '/sdks/integrations/skills'},
      {label: 'Custom Hook', icon: LuPlug,                      href: '/sdks/integrations'},
    ]} />
  );
}

export function LLMProvidersGrid(): React.JSX.Element {
  return (
    <IconGrid items={[
      {label: 'OpenAI',         icon: SiOpenai},
      {label: 'Anthropic',      icon: SiAnthropic},
      {label: 'Google Gemini',  icon: SiGooglegemini},
      {label: 'Groq',           icon: LuZap},
      {label: 'Ollama',         icon: SiOllama},
      {label: 'LM Studio',      icon: LuBrainCog},
      {label: 'MiniMax',        icon: LuSparkles},
      {label: 'AWS Bedrock',    icon: LuCloud},
      {label: 'LiteLLM 100+',   icon: LuLayers},
      {label: 'OpenAI Compat',  icon: OpenAICompatibleIcon},
    ]} />
  );
}
