import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Bot, User, Wrench, AlertCircle } from 'lucide-react'
import type { ChatMessage } from '../../types'
import clsx from 'clsx'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'

interface Props {
  message: ChatMessage
}

const TOOL_LABELS: Record<string, string> = {
  enterprise_graph_search: 'Граф производства',
  enterprise_docs_search:  'Документация',
  inventory_sql_search:    'Склад',
  blueprint_vision:        'Анализ чертежа',
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user'
  const isTool = message.role === 'tool'
  const time = format(new Date(message.created_at), 'HH:mm', { locale: ru })

  if (isTool) {
    const label = TOOL_LABELS[message.tool_name ?? ''] ?? message.tool_name
    return (
      <div className="flex items-start gap-2 py-1 px-4 animate-fade-in">
        <div className="mt-0.5 w-5 h-5 rounded flex items-center justify-center bg-amber-500/15 shrink-0">
          <Wrench size={11} className="text-amber-400" />
        </div>
        <div className="text-xs text-slate-500 leading-relaxed">
          <span className="text-amber-400 font-medium">{label}</span>
          {' '}&mdash; данные получены
        </div>
      </div>
    )
  }

  return (
    <div
      className={clsx(
        'flex gap-3 px-4 py-3 group animate-fade-in',
        isUser ? 'flex-row-reverse' : 'flex-row',
      )}
    >
      {/* Аватар */}
      <div
        className={clsx(
          'w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5',
          isUser ? 'bg-accent/20' : 'bg-surface-700',
        )}
      >
        {isUser ? (
          <User size={16} className="text-accent-light" />
        ) : (
          <Bot size={16} className="text-slate-400" />
        )}
      </div>

      {/* Контент */}
      <div className={clsx('flex flex-col gap-1 max-w-[78%]', isUser ? 'items-end' : 'items-start')}>
        <div
          className={clsx(
            'px-4 py-3 rounded-2xl text-sm leading-relaxed shadow-sm',
            isUser
              ? 'bg-accent text-white rounded-tr-sm'
              : 'bg-surface-800 border border-surface-700 rounded-tl-sm',
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose-chat">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ node, className, children, ...props }) {
                    const match = /language-(\w+)/.exec(className || '')
                    const isBlock = !!(props as { inline?: boolean }).inline === false && match

                    return isBlock ? (
                      <SyntaxHighlighter
                        style={vscDarkPlus as Record<string, React.CSSProperties>}
                        language={match![1]}
                        PreTag="div"
                        customStyle={{
                          margin: 0,
                          borderRadius: '0.5rem',
                          fontSize: '0.8rem',
                          background: '#0f172a',
                        }}
                      >
                        {String(children).replace(/\n$/, '')}
                      </SyntaxHighlighter>
                    ) : (
                      <code className={className} {...props}>
                        {children}
                      </code>
                    )
                  },
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
        <span className="text-xs text-slate-600 px-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {time}
        </span>
      </div>
    </div>
  )
}

// Стриминговое сообщение ассистента (пока генерируется)
interface StreamingProps {
  text: string
  status: string
  activeTools: string[]
}

export function StreamingBubble({ text, status, activeTools }: StreamingProps) {
  const showTyping = !text && !activeTools.length

  return (
    <div className="flex gap-3 px-4 py-3 animate-fade-in">
      {/* Аватар */}
      <div className="w-8 h-8 rounded-lg bg-surface-700 flex items-center justify-center shrink-0 mt-0.5">
        <Bot size={16} className="text-slate-400" />
      </div>

      <div className="flex flex-col gap-2 max-w-[78%]">
        {/* Статус / инструменты */}
        {(status || activeTools.length > 0) && (
          <div className="flex flex-wrap gap-2">
            {activeTools.map((tool) => (
              <span
                key={tool}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full
                           bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs"
              >
                <Wrench size={10} className="animate-spin" />
                {TOOL_LABELS[tool] ?? tool}
              </span>
            ))}
            {status && !activeTools.length && (
              <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
                {status}
              </span>
            )}
          </div>
        )}

        {/* Текст ответа или индикатор */}
        <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-surface-800 border border-surface-700 text-sm">
          {showTyping ? (
            <div className="typing-dots flex items-center h-5">
              <span />
              <span />
              <span />
            </div>
          ) : (
            <div className="prose-chat">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
              <span className="inline-block w-0.5 h-4 bg-accent-light ml-0.5 animate-pulse" />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
