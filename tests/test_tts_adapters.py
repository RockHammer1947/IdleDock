"""Exercise adapter API contracts using fake libraries; never import a real ML runtime."""
import os
import types
import unittest
from unittest.mock import patch
from h3queue import tts_runner


class Samples(list):
    ndim=1
    @property
    def shape(self):return (len(self),)
    @property
    def size(self):return len(self)
    def copy(self):return Samples(self)


class TTSAdapterTests(unittest.TestCase):
    def spec(self):
        return {'deployment':'/fake/deployment','model_path':'/fake/model','profile':'qwen-custom','text':'literal $(not a command)',
                'language':'zh','seed':42,'profile_config':{'runtime':'mlx-audio','generation':{}},'options':{'voice':'custom-voice'}}

    def test_mlx_audio_options_and_chunks(self):
        seen={}
        def generate(**kwargs):
            seen.update(kwargs)
            yield types.SimpleNamespace(audio=Samples([.1,.2]),sample_rate=24000)
            yield types.SimpleNamespace(audio=Samples([.3]),sample_rate=24000)
        utils=types.ModuleType('mlx_audio.tts.utils');utils.load_model=lambda path:types.SimpleNamespace(generate=generate)
        core=types.ModuleType('mlx.core');core.eval=lambda x:None
        mlx=types.ModuleType('mlx');mlx.core=core
        numpy=types.ModuleType('numpy');numpy.float32='float32';numpy.asarray=lambda a,dtype:Samples(a)
        numpy.concatenate=lambda chunks,axis:[v for chunk in chunks for v in chunk]
        modules={'mlx':mlx,'mlx.core':core,'numpy':numpy,'soundfile':types.ModuleType('soundfile'),
                 'mlx_audio':types.ModuleType('mlx_audio'),'mlx_audio.tts':types.ModuleType('mlx_audio.tts'),'mlx_audio.tts.utils':utils}
        with patch.dict('sys.modules',modules),patch.object(tts_runner,'write_audio') as write:
            tts_runner.mlx_audio(self.spec(),'/fake/output.wav')
        self.assertEqual(seen['voice'],'custom-voice');self.assertEqual(seen['lang_code'],'Chinese')
        self.assertFalse(seen['stream']);self.assertEqual(seen['text'],'literal $(not a command)')
        write.assert_called_once_with('/fake/output.wav',[.1,.2,.3],24000)

    def test_indextts_uses_pinned_reference_and_generation_options(self):
        seen={}
        class Runtime:
            def __init__(self,**kwargs):seen['runtime']=kwargs
            def load(self,path):seen['model']=path
            def generate(self,*args,**kwargs):seen['args']=args;seen['kwargs']=kwargs
        runtime=types.ModuleType('mlx_indextts.runtime');runtime.TTSRuntime=Runtime;runtime.GenerateOptions=types.SimpleNamespace
        sound=types.ModuleType('soundfile');sound.read=lambda path,dtype:([.1],24000)
        spec=self.spec();spec.update(profile='indextts25',reference_audio='/fake/ref.wav',options={'diffusion_steps':25,'use_gpt_latent':True})
        with patch.dict('sys.modules',{'mlx_indextts':types.ModuleType('mlx_indextts'),'mlx_indextts.runtime':runtime,'soundfile':sound}),patch.object(tts_runner,'write_audio'),patch.dict(os.environ,{},clear=False):
            tts_runner.indextts(spec,'/fake/output.wav')
            self.assertEqual(os.environ['INDEXTTS_W2V_BERT_DIR'],'/fake/deployment/TTS/runtimes/models/w2v-bert-2.0')
        self.assertEqual(seen['args'][1],'/fake/ref.wav');self.assertEqual(seen['kwargs']['profile'],'v25')
        self.assertEqual(seen['kwargs']['options'].diffusion_steps,25)

    def test_auk_flash_uses_its_configuration_and_step_count(self):
        seen={}
        class Runtime:
            def __init__(self,*args,**kwargs):seen['init']=args
            def generate(self,*args,**kwargs):seen['kwargs']=kwargs;return [.1],24000
        infer=types.ModuleType('auk_mlx.infer');infer.AukMLX=Runtime;infer.GenerateOptions=types.SimpleNamespace
        spec=self.spec();spec.update(profile='auk-flash',reference_audio='/fake/ref.wav',options={})
        with patch.dict('sys.modules',{'auk_mlx':types.ModuleType('auk_mlx'),'auk_mlx.infer':infer}),patch.object(tts_runner,'write_audio'):
            tts_runner.auk(spec,'/fake/output.wav')
        self.assertEqual(seen['init'][1],'/fake/model/config_flash.yaml')
        self.assertEqual(seen['kwargs']['opts'].nfe,4);self.assertEqual(seen['kwargs']['audio_path'],'/fake/ref.wav')


if __name__=='__main__':unittest.main()
