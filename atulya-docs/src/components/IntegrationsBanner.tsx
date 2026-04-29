/**
 *
 * Animated marquee strip — all Atulya SDK clients, integrations, and LLM providers.
 * Infinite scroll animation via CSS; hover pauses and highlights in Atulya red.
 */
import React from 'react';
import type {IconType} from 'react-icons';
import {SiPython, SiGo, SiOpenai, SiAnthropic, SiGooglegemini, SiOllama, SiVercel} from 'react-icons/si';
import {LuTerminal, LuZap, LuBrainCog, LuSparkles, LuGlobe, LuCloud, LuLayers} from 'react-icons/lu';
import styles from './IntegrationsBanner.module.css';

interface BannerItem {
  label: string;
  icon?: IconType;
  imgSrc?: string;
  href?: string;
}

const ITEMS: BannerItem[] = [
  // Clients
  {label: 'Python',      icon: SiPython,   href: '/sdks/python'},
  {label: 'TypeScript',  imgSrc: '/img/icons/typescript.png', href: '/sdks/nodejs'},
  {label: 'Go',          icon: SiGo,       href: '/sdks/go'},
  {label: 'CLI',         icon: LuTerminal, href: '/sdks/cli'},
  {label: 'HTTP',        icon: LuGlobe,    href: '/developer/api/quickstart'},
  // Integrations
  {label: 'MCP Server',   imgSrc: '/img/icons/mcp.png',      href: '/sdks/integrations/local-mcp'},
  {label: 'LiteLLM',      imgSrc: '/img/icons/litellm.png',  href: '/sdks/integrations/litellm'},
  {label: 'OpenClaw',     imgSrc: '/img/icons/openclaw.png', href: '/sdks/integrations/openclaw'},
  {label: 'Vercel AI',    icon: SiVercel,                    href: '/sdks/integrations/ai-sdk'},
  {label: 'Skills',       imgSrc: '/img/icons/skills.png',   href: '/sdks/integrations/skills'},
  // LLM Providers
  {label: 'OpenAI',        icon: SiOpenai},
  {label: 'Anthropic',     icon: SiAnthropic},
  {label: 'Gemini',        icon: SiGooglegemini},
  {label: 'Groq',          icon: LuZap},
  {label: 'Ollama',        icon: SiOllama},
  {label: 'LM Studio',     icon: LuBrainCog},
  {label: 'MiniMax',       icon: LuSparkles},
  {label: 'AWS Bedrock',   icon: LuCloud},
  {label: 'LiteLLM 100+',  icon: LuLayers},
];

function BannerItemComponent({item}: {item: BannerItem}) {
  const content = (
    <span className={styles.item}>
      <span className={styles.itemIcon}>
        {item.icon && <item.icon size={16} />}
        {item.imgSrc && (
          <img src={item.imgSrc} alt={item.label} width={16} height={16} style={{objectFit: 'contain'}} />
        )}
      </span>
      <span className={styles.itemLabel}>{item.label}</span>
    </span>
  );
  return item.href
    ? <a href={item.href} className={styles.itemLink}>{content}</a>
    : <span>{content}</span>;
}

export default function IntegrationsBanner(): React.JSX.Element {
  // Double the list so the scroll loop is seamless
  const doubled = [...ITEMS, ...ITEMS];
  return (
    <div className={styles.banner}>
      <div className={styles.track}>
        {doubled.map((item, i) => (
          <BannerItemComponent key={`${item.label}-${i}`} item={item} />
        ))}
      </div>
    </div>
  );
}
