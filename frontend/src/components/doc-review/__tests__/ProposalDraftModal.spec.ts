import { createI18n } from "vue-i18n";
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import zh from "@/locales/zh.json";
import ProposalDraftModal from "../ProposalDraftModal.vue";

const i18n = createI18n({
  legacy: false,
  locale: "zh",
  messages: { zh },
});

type PickerSource = {
  id: string;
  quote: string;
  version: string;
  blockId?: string;
  creator?: string;
  messageCount?: number;
  charStart?: number;
  charEnd?: number;
  anchorStatus?: "valid" | "missing";
  messages?: Array<{
    id: string;
    role: "user" | "ai" | "system";
    content: string;
    creator?: string;
    createdAt?: string;
  }>;
};

const sourceOptions: PickerSource[] = [
  {
    id: "thread-a",
    quote: "本次发布需要保留旧接口兼容",
    version: "原引用 v1",
    blockId: "blk-12",
    creator: "李明",
    messageCount: 3,
    charStart: 120,
    charEnd: 148,
    anchorStatus: "valid",
    messages: [
      { id: "m-a-1", role: "user", content: "旧接口还有调用方，需要保留兼容层。", creator: "李明", createdAt: "2026-07-01T10:00:00Z" },
      { id: "m-a-2", role: "ai", content: "建议保留兼容层并在下个版本移除。", createdAt: "2026-07-01T10:01:00Z" },
    ],
  },
  {
    id: "thread-b",
    quote: "回滚策略需要补充触发条件",
    version: "原引用 v2",
    blockId: "blk-18",
    creator: "王芳",
    messageCount: 2,
    charStart: 32,
    charEnd: 45,
    anchorStatus: "valid",
    messages: [
      { id: "m-b-1", role: "user", content: "回滚触发条件目前不明确。", creator: "王芳" },
    ],
  },
  {
    id: "thread-c",
    quote: "灰度阶段需要增加监控指标",
    version: "原引用 v3",
    blockId: "blk-24",
    creator: "赵磊",
    messageCount: 4,
    charStart: 8,
    charEnd: 24,
    anchorStatus: "valid",
    messages: [
      { id: "m-c-1", role: "system", content: "该讨论已由赵磊标记为已解决。", createdAt: "2026-07-02T09:30:00Z" },
    ],
  },
];

const duplicateSources: PickerSource[] = [
  {
    id: "thread-dup-1",
    quote: "超时阈值需要确认",
    version: "原引用 v1",
    blockId: "blk-3",
    creator: "李明",
    messageCount: 2,
    charStart: 0,
    charEnd: 8,
    anchorStatus: "valid",
    messages: [
      { id: "dup-1-msg", role: "user", content: "这里指的是网关超时。", creator: "李明" },
    ],
  },
  {
    id: "thread-dup-2",
    quote: "超时阈值需要确认",
    version: "原引用 v2",
    blockId: "blk-8",
    creator: "王芳",
    messageCount: 2,
    charStart: 40,
    charEnd: 48,
    anchorStatus: "valid",
    messages: [
      { id: "dup-2-msg", role: "user", content: "这里指的是任务执行超时。", creator: "王芳" },
    ],
  },
];

const mountPicker = (options: PickerSource[] = sourceOptions) =>
  mount(ProposalDraftModal, {
    props: {
      visible: true,
      proposal: null,
      selectingSources: true,
      canRewrite: true,
      sourceOptions: options,
    },
    global: { plugins: [i18n] },
  });

describe("ProposalDraftModal source picker", () => {
  it("renders each resolved discussion as a selectable card", () => {
    const wrapper = mountPicker();
    const items = wrapper.findAll(".picker-item");
    expect(items).toHaveLength(3);
    expect(items[0].text()).toContain("本次发布需要保留旧接口兼容");
    expect(items[0].text()).toContain("原引用 v1");
  });

  it("tracks checked cards and only emits selected ids", async () => {
    const wrapper = mountPicker();
    const inputs = wrapper.findAll<HTMLInputElement>(".picker-input");

    await inputs[0].setValue(true);
    await inputs[2].setValue(true);

    expect(wrapper.findAll(".picker-item.selected")).toHaveLength(2);
    expect(wrapper.find(".actions-status").text()).toContain("已选 2 条讨论");

    const generate = wrapper.findAll("button").find(button => button.text().includes("联合生成"));
    await generate!.trigger("click");
    expect(wrapper.emitted("generate")?.[0]).toEqual([["thread-a", "thread-c"]]);
  });

  it("supports select all and clear selection", async () => {
    const wrapper = mountPicker();
    const toggle = wrapper.findAll("button").find(button => button.text() === "全选");

    await toggle!.trigger("click");
    expect(wrapper.findAll(".picker-item.selected")).toHaveLength(3);

    const clear = wrapper.findAll("button").find(button => button.text() === "清空选择");
    await clear!.trigger("click");
    expect(wrapper.findAll(".picker-item.selected")).toHaveLength(0);
  });

  it("filters cards by quote or version", async () => {
    const wrapper = mountPicker([
      ...sourceOptions,
      { id: "thread-d", quote: "发布窗口需要避开节假日", version: "原引用 v4" },
      { id: "thread-e", quote: "通知模板需要同步更新", version: "原引用 v5" },
    ]);
    await wrapper.find('input[type="search"]').setValue("v2");

    const items = wrapper.findAll(".picker-item");
    expect(items).toHaveLength(1);
    expect(items[0].text()).toContain("回滚策略需要补充触发条件");
  });

  it("distinguishes discussions that share the same selected quote", () => {
    const wrapper = mountPicker(duplicateSources);
    const items = wrapper.findAll(".picker-item");

    expect(items).toHaveLength(2);
    expect(items[0].text()).toContain("#blk-3");
    expect(items[0].text()).toContain("李明");
    expect(items[0].text()).toContain("第 0–8 字");
    expect(items[1].text()).toContain("#blk-8");
    expect(items[1].text()).toContain("王芳");
    expect(items[1].text()).toContain("第 40–48 字");
    expect(items[0].text()).toContain("同文 2 条讨论");
    expect(items[1].text()).toContain("同文 2 条讨论");
    expect(items[0].find(".picker-input").attributes("aria-label")).toContain("#blk-3");
  });

  it("expands a discussion to show its own messages", async () => {
    const wrapper = mountPicker(duplicateSources);

    await wrapper.findAll(".picker-toggle")[0].trigger("click");

    const first = wrapper.findAll(".picker-item")[0];
    expect(first.find(".picker-thread").exists()).toBe(true);
    expect(first.text()).toContain("这里指的是网关超时。");
    expect(first.text()).not.toContain("这里指的是任务执行超时。");
    expect(first.find(".picker-toggle").attributes("aria-expanded")).toBe("true");

    await first.find(".picker-toggle").trigger("click");
    expect(wrapper.findAll(".picker-item")[0].find(".picker-thread").exists()).toBe(false);
  });

  it("selects by discussion id even when quotes are identical", async () => {
    const wrapper = mountPicker(duplicateSources);
    await wrapper.findAll<HTMLInputElement>(".picker-input")[1].setValue(true);

    const generate = wrapper.findAll("button").find(button => button.text().includes("联合生成"));
    await generate!.trigger("click");
    expect(wrapper.emitted("generate")?.[0]).toEqual([["thread-dup-2"]]);
  });

  it("shows an empty state when there are no resolved discussions", () => {
    const wrapper = mountPicker([]);
    expect(wrapper.find(".picker-empty").exists()).toBe(true);
    expect(wrapper.find(".picker-list").exists()).toBe(false);
  });
});
