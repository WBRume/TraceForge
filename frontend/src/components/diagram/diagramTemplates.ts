import { blankDiagram, makeEdge, makeNode, type DiagramEdge, type DiagramNode, type Shape } from './diagramModel'
import { layoutHierarchy } from './diagramHierarchy'

export const templateNames = [
  'flow', 'lanes', 'classes', 'usecases', 'sequence', 'state', 'entity', 'architecture', 'network', 'mindmap', 'organization',
] as const
export type DiagramTemplate = (typeof templateNames)[number]
type Label = readonly [zh: string, en: string]

export function createTemplate(template: DiagramTemplate, title: string, chinese: boolean) {
  const doc = blankDiagram(title)
  const word = (label: Label) => label[chinese ? 0 : 1]
  const node = (shape: Shape, x: number, y: number, label: Label, extra?: Partial<DiagramNode>) => {
    const result = { ...makeNode(shape, { x, y }, word(label)), ...extra }
    doc.nodes.push(result)
    return result
  }
  const edge = (source: DiagramNode, target: DiagramNode, label: Label = ['', ''], extra?: Partial<DiagramEdge>) => {
    doc.edges.push({ ...makeEdge(source, target), label: word(label), ...extra })
  }

  switch (template) {
    case 'flow': {
      const start = node('terminal', 0, 131, ['开始', 'Start'])
      const submit = node('process', 218, 131, ['提交申请', 'Submit request'])
      const review = node('decision', 436, 110, ['审批通过？', 'Approved?'])
      const update = node('process', 664, 64, ['更新记录', 'Update record'])
      const retry = node('document', 664, 238, ['补充材料', 'Request revisions'])
      const end = node('terminal', 886, 64, ['完成', 'Done'])
      edge(start, submit)
      edge(submit, review)
      edge(review, update, ['是', 'Yes'])
      edge(review, retry, ['否', 'No'])
      edge(update, end)
      break
    }
    case 'lanes': {
      const requester = node('lane', 0, 0, ['申请人', 'Requester'], { width: 818 })
      const reviewer = node('lane', 0, 176, ['审核人', 'Reviewer'], { width: 818, fill: '#e7f4fa' })
      const submit = node('terminal', requester.x + 134, requester.y + 55, ['提交申请', 'Submit request'])
      const check = node('process', reviewer.x + 372, reviewer.y + 55, ['审核材料', 'Review materials'])
      const close = node('document', requester.x + 612, requester.y + 55, ['接收结果', 'Receive result'])
      edge(submit, check)
      edge(check, close, ['审核完成', 'Review complete'])
      break
    }
    case 'classes': {
      const repository = node('interface', 278, 0, ['OrderRepository', 'OrderRepository'], {
        detail: '', operations: '+ find(id): Order\n+ save(order): void',
      })
      const store = node('class', 278, 236, ['SqlOrderRepository', 'SqlOrderRepository'], {
        detail: '− connection: DataSource', operations: '+ find(id): Order\n+ save(order): void',
      })
      const order = node('class', 0, 236, ['Order', 'Order'], {
        detail: '− id: UUID\n− state: OrderState', operations: '+ approve(): void',
      })
      const line = node('class', 556, 236, ['OrderItem', 'OrderItem'], {
        detail: '− sku: String\n− amount: Integer', operations: '+ subtotal(): Decimal',
      })
      edge(store, repository, ['', ''], { relation: 'realization' })
      edge(store, order, ['', ''], { relation: 'dependency' })
      edge(order, line, ['包含', 'Contains'], { relation: 'composition', routing: 'curve' })
      break
    }
    case 'usecases': {
      node('frame', 176, 0, ['工单系统', 'Ticket system'], { width: 540, height: 320 })
      const requester = node('actor', 0, 94, ['申请人', 'Requester'])
      const agent = node('actor', 790, 94, ['处理人', 'Agent'])
      const submit = node('usecase', 230, 74, ['提交工单', 'Submit ticket'])
      const query = node('usecase', 230, 202, ['查询进度', 'Check status'])
      const review = node('usecase', 487, 74, ['处理工单', 'Resolve ticket'])
      edge(requester, submit, ['', ''], { relation: 'association' })
      edge(requester, query, ['', ''], { relation: 'association' })
      edge(agent, review, ['', ''], { relation: 'association' })
      break
    }
    case 'sequence': {
      const client = node('lifeline', 0, 0, ['客户端', 'Client'])
      const api = node('lifeline', 286, 0, ['订单服务', 'Order service'])
      const db = node('lifeline', 572, 0, ['数据库', 'Database'])
      edge(client, api, ['创建订单', 'Create order'], { offset: 98 })
      edge(api, db, ['保存订单', 'Persist order'], { offset: 153 })
      edge(db, api, ['返回订单编号', 'Return order ID'], { relation: 'reply', offset: 205 })
      edge(api, client, ['返回创建结果', 'Return result'], { relation: 'reply', offset: 265 })
      break
    }
    case 'state': {
      const start = node('initial', 0, 18, ['', ''])
      const draft = node('state', 112, 0, ['草稿', 'Draft'])
      const pending = node('state', 370, 0, ['待审批', 'Pending review'])
      const done = node('state', 620, 0, ['已完成', 'Complete'])
      const final = node('final', 870, 17, ['', ''])
      edge(start, draft)
      edge(draft, pending, ['提交', 'Submit'])
      edge(pending, draft, ['退回', 'Return'], { routing: 'curve' })
      edge(pending, done, ['批准', 'Approve'])
      edge(done, final)
      break
    }
    case 'entity': {
      const customer = node('entity', 0, 0, ['客户', 'Customer'], { detail: 'PK  id: UUID\n      name: String' })
      const order = node('entity', 320, 0, ['订单', 'Order'], { detail: 'PK  id: UUID\nFK  customer_id: UUID\n      created_at: DateTime' })
      const item = node('entity', 640, 0, ['订单明细', 'Order line'], { detail: 'PK  id: UUID\nFK  order_id: UUID\n      quantity: Integer' })
      edge(customer, order, ['下单', 'Places'], { relation: 'many' })
      edge(order, item, ['包含', 'Contains'], { relation: 'many' })
      break
    }
    case 'architecture': {
      const client = node('client', 0, 148, ['用户客户端', 'User client'])
      const gateway = node('service', 220, 148, ['接入网关', 'API gateway'], { detail: 'HTTPS / 443' })
      const orders = node('service', 457, 148, ['订单服务', 'Order service'], { detail: 'REST API' })
      const store = node('database', 731, 0, ['订单数据库', 'Order database'], { detail: 'PostgreSQL' })
      const bus = node('queue', 731, 155, ['订单事件', 'Order events'], { detail: 'orders.created' })
      const worker = node('server', 731, 307, ['结算处理器', 'Settlement worker'], { detail: 'Consumer' })
      edge(client, gateway, ['HTTPS', 'HTTPS'])
      edge(gateway, orders, ['路由转发', 'Route'])
      edge(orders, store, ['读写', 'Read / write'])
      edge(orders, bus, ['发布', 'Publish'])
      edge(bus, worker, ['消费', 'Consume'])
      break
    }
    case 'network': {
      node('frame', 474, 0, ['内网', 'Internal network'], { width: 488, height: 340 })
      const internet = node('cloud', 0, 130, ['互联网', 'Internet'])
      const firewall = node('firewall', 239, 139, ['边界防火墙', 'Perimeter firewall'], { detail: 'NAT / ACL' })
      const router = node('router', 504, 139, ['核心路由器', 'Core router'], { detail: '10.10.0.1' })
      const office = node('client', 753, 62, ['办公终端', 'Office clients'], { detail: 'VLAN 10' })
      const server = node('server', 753, 237, ['内网服务器', 'Internal server'], { detail: 'VLAN 20' })
      edge(internet, firewall, ['公网', 'WAN'], { relation: 'network' })
      edge(firewall, router, ['上行链路', 'Uplink'], { relation: 'network' })
      edge(router, office, ['', ''], { relation: 'network' })
      edge(router, server, ['', ''], { relation: 'network' })
      break
    }
    case 'mindmap': {
      const root = node('topicRoot', 425, 166, ['版本发布', 'Release'])
      const build = node('topic', 0, 0, ['研发准备', 'Engineering'])
      const qa = node('topic', 0, 0, ['质量验证', 'Validation'])
      const operations = node('topic', 0, 0, ['上线计划', 'Rollout'])
      const fixes = node('topic', 0, 0, ['合入修复', 'Merge fixes'])
      const review = node('topic', 0, 0, ['回归检查', 'Run regression'])
      const checklist = node('topic', 0, 0, ['检查依赖', 'Check dependencies'])
      const release = node('topic', 0, 0, ['发布与回滚', 'Deploy and roll back'])
      edge(root, build, ['', ''], { stroke: '#3482ad' })
      edge(root, qa, ['', ''], { stroke: '#5574a1' })
      edge(root, operations, ['', ''], { stroke: '#3482ad' })
      edge(build, fixes, ['', ''], { stroke: '#3482ad' })
      edge(qa, review, ['', ''], { stroke: '#5574a1' })
      edge(qa, checklist, ['', ''], { stroke: '#5574a1' })
      edge(operations, release, ['', ''], { stroke: '#3482ad' })
      doc.nodes = layoutHierarchy(doc, new Set(), true)
      break
    }
    case 'organization': {
      const lead = node('person', 332, 0, ['产品交付组', 'Delivery group'], { detail: word(['负责人', 'Group lead']) })
      const eng = node('person', 0, 0, ['工程小组', 'Engineering'], { detail: word(['技术主管', 'Engineering lead']) })
      const ops = node('person', 0, 0, ['运营小组', 'Operations'], { detail: word(['运营主管', 'Operations lead']) })
      const api = node('person', 0, 0, ['服务端开发', 'Backend development'], { detail: word(['服务与数据', 'Services and data']) })
      const ui = node('person', 0, 0, ['客户端开发', 'Client development'], { detail: word(['桌面与前端', 'Desktop and web']) })
      const support = node('person', 0, 0, ['客户支持', 'Customer support'], { detail: word(['排查与反馈', 'Triage and feedback']) })
      edge(lead, eng)
      edge(lead, ops)
      edge(eng, api)
      edge(eng, ui)
      edge(ops, support)
      doc.nodes = layoutHierarchy(doc, new Set(), false)
      break
    }
  }
  return doc
}
