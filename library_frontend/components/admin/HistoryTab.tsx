'use client'

interface AdminAction {
  id: number
  admin_id: number
  admin_name: string
  action: 'create' | 'edit' | 'delete' | 'publish' | 'unpublish'
  entity_type: 'material' | 'category' | 'tag'
  entity_id?: number
  entity_title?: string
  details?: string
  created_at: string
}

interface HistoryTabProps {
  adminHistory: AdminAction[]
  loadingHistory: boolean
}

/**
 * Таб истории действий админов
 */
export function HistoryTab({ adminHistory, loadingHistory }: HistoryTabProps) {
  return (
    <div className="bg-white/80 backdrop-blur-lg rounded-2xl border border-[#E8D4BA]/30 overflow-hidden">
      <div className="p-4 border-b border-[#E8D4BA]/30">
        <h2 className="text-lg font-bold text-[#5D4E3A]">📝 История действий</h2>
        <p className="text-sm text-[#8B8279]">Все действия админов в библиотеке</p>
      </div>
      
      {loadingHistory ? (
        <div className="p-8 text-center text-[#8B8279]">Загрузка...</div>
      ) : adminHistory.length === 0 ? (
        <div className="p-8 text-center text-[#8B8279]">История пуста</div>
      ) : (
        <div className="divide-y divide-[#E8D4BA]/30 max-h-[600px] overflow-y-auto">
          {adminHistory.map((action) => {
            const actionConfig = {
              create: { emoji: '➕', color: 'text-green-600', bg: 'bg-green-50', label: 'создал(а)' },
              edit: { emoji: '✏️', color: 'text-yellow-600', bg: 'bg-yellow-50', label: 'изменил(а)' },
              delete: { emoji: '🗑️', color: 'text-red-600', bg: 'bg-red-50', label: 'удалил(а)' },
              publish: { emoji: '📢', color: 'text-blue-600', bg: 'bg-blue-50', label: 'опубликовал(а)' },
              unpublish: { emoji: '📴', color: 'text-gray-600', bg: 'bg-gray-50', label: 'снял(а) с публикации' }
            }[action.action] || { emoji: '📝', color: 'text-gray-600', bg: 'bg-gray-50', label: action.action }
            
            const entityLabel = {
              material: 'материал',
              category: 'категорию',
              tag: 'тег'
            }[action.entity_type] || action.entity_type
            
            return (
              <div key={action.id} className={`p-4 flex items-start gap-3 ${actionConfig.bg}`}>
                <span className="text-xl">{actionConfig.emoji}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-[#5D4E3A]">
                    <span className="font-medium">{action.admin_name}</span>
                    {' '}
                    <span className={actionConfig.color}>{actionConfig.label}</span>
                    {' '}
                    {entityLabel}
                    {action.entity_title && (
                      <span className="font-medium"> «{action.entity_title}»</span>
                    )}
                  </p>
                  <p className="text-xs text-[#8B8279] mt-1">
                    {new Date(action.created_at).toLocaleString('ru-RU', {
                      day: 'numeric',
                      month: 'short',
                      hour: '2-digit',
                      minute: '2-digit'
                    })}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
